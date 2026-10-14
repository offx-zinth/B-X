"""BFL: Business Formula Language — safe subset, no arbitrary code.
Refs: Type.property (e.g. Inventory.available). Fns: SUM AVG MIN MAX IF ABS ROUND COUNT RATE DELTA CLAMP.
Deterministic: no I/O, no randomness, no arbitrary Python/JS. Missing refs resolve to 0.0
with a warning (never silently invented — warnings are returned explicitly).
"""
from __future__ import annotations
import re, math

FUNCTIONS = {"SUM","AVG","MIN","MAX","IF","ABS","ROUND","COUNT","RATE","DELTA","CLAMP"}
# Ref forms: Type.property and prev.Type.property (previous-day read for stocks).
REF_RE = re.compile(r"\b(prev\.)?([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")
TOKEN_RE = re.compile(r"\s*(\d+\.?\d*|[A-Za-z_][A-Za-z0-9_.]*|>=|<=|==|!=|[+\-*/(),><=])")

def extract_refs(expr: str) -> list[str]:
    refs = REF_RE.findall(expr)
    out = []
    for prev, a, b in refs:
        if a.upper() in FUNCTIONS: continue
        out.append(f"{prev}{a}.{b}")
    seen, res = set(), []
    for r in out:
        if r not in seen: seen.add(r); res.append(r)
    return res

def _fn_sum(*a): return sum(a)
def _fn_avg(*a): return sum(a)/len(a) if a else 0
def _fn_min(*a): return min(a) if a else 0
def _fn_max(*a): return max(a) if a else 0
def _fn_if(c, t, f): return t if c else f
def _fn_abs(x): return abs(x)
def _fn_round(x, n=0): return round(x, int(n))
def _fn_count(*a): return len(a)
def _fn_rate(a, b): return (a/b) if b else 0
def _fn_delta(a, b): return a-b
def _fn_clamp(x, lo, hi):
    lo, hi = float(lo), float(hi)
    if lo > hi: lo, hi = hi, lo
    return max(lo, min(float(x), hi))

SAFE_FNS = {"SUM":_fn_sum,"AVG":_fn_avg,"MIN":_fn_min,"MAX":_fn_max,"IF":_fn_if,"ABS":_fn_abs,"ROUND":_fn_round,"COUNT":_fn_count,"RATE":_fn_rate,"DELTA":_fn_delta,"CLAMP":_fn_clamp}

class Parser:
    def __init__(self, tokens, resolver):
        self.t = tokens; self.p = 0; self.resolve = resolver
    def peek(self): return self.t[self.p] if self.p < len(self.t) else None
    def eat(self, v=None):
        cur = self.peek()
        if cur is None: raise ValueError("unexpected end")
        if v is not None and cur != v: raise ValueError(f"expected {v} got {cur}")
        self.p += 1; return cur
    def parse(self):
        v = self.cmp()
        if self.peek() is not None: raise ValueError(f"unexpected token {self.peek()}")
        return v
    def cmp(self):
        l = self.add()
        while self.peek() in (">","<",">=","<=","=","==","!="):
            op = self.eat(); r = self.add()
            l = (l > r) if op==">" else (l < r) if op=="<" else (l>=r) if op==">=" else (l<=r) if op=="<=" else (1.0 if l==r else 0.0) if op in ("=","==") else (1.0 if l!=r else 0.0)
        return l
    def add(self):
        l = self.mul()
        while self.peek() in ("+","-"):
            op=self.eat(); r=self.mul(); l = l+r if op=="+" else l-r
        return l
    def mul(self):
        l = self.un()
        while self.peek() in ("*","/"):
            op=self.eat(); r=self.un(); l = l*r if op=="*" else (l/r if r!=0 else float("inf"))
        return l
    def un(self):
        if self.peek()=="-": self.eat(); return -self.un()
        if self.peek()=="+": self.eat(); return self.un()
        return self.atom()
    def atom(self):
        cur = self.peek()
        if cur is None: raise ValueError("unexpected end in atom")
        if re.fullmatch(r"\d+\.?\d*", cur or ""):
            self.eat(); return float(cur)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", cur or ""):
            name = self.eat()
            if self.peek()=="(":
                if name.upper() not in SAFE_FNS: raise ValueError(f"unknown function {name}")
                self.eat("("); args=[]
                if self.peek() != ")":
                    args.append(self.cmp())
                    while self.peek()==",":
                        self.eat(","); args.append(self.cmp())
                self.eat(")")
                return float(SAFE_FNS[name.upper()](*args))
            if "." in name:
                return float(self.resolve(name))
            raise ValueError(f"bare identifier {name}; use Type.property")
        if cur=="(":
            self.eat("("); v=self.cmp(); self.eat(")"); return v
        raise ValueError(f"unexpected {cur}")

def tokenize(expr: str) -> list[str]:
    toks=[]; i=0
    while i < len(expr):
        if expr[i].isspace(): i+=1; continue
        m = TOKEN_RE.match(expr, i)
        if not m: raise ValueError(f"bad char at {i}: {expr[i:][:20]}")
        toks.append(m.group(1)); i=m.end()
    return toks

def evaluate(expr: str, context: dict[str, float]) -> float:
    """context: {'Inventory.available': 5000, ...} missing refs -> 0.0"""
    res = evaluate_detailed(expr, context)
    if res["error"]:
        raise ValueError(res["error"])
    return res["value"]


def evaluate_detailed(expr: str, context: dict[str, float]) -> dict:
    """Deterministic evaluation producing value + dependencies + trace + errors + warnings.

    Never raises for missing refs (warning instead). Raises ValueError only for
    syntax / unknown-function / disallowed-character errors — callers convert
    these into ``error`` strings via this wrapper's try/except contract.
    """
    warnings: list[str] = []
    trace: list[str] = []
    deps = extract_refs(expr)
    for d in deps:
        if d not in (context or {}):
            warnings.append(f"missing ref {d} resolved to 0.0")
    def resolve(ref: str) -> float:
        v = (context or {}).get(ref, 0.0)
        try:
            fv = float(v)
        except (ValueError, TypeError):
            warnings.append(f"non-numeric ref {ref} resolved to 0.0")
            return 0.0
        trace.append(f"{ref}={fv}")
        return fv
    try:
        # validate fns: reject unknown CALL( pattern
        for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", expr):
            if m.group(1).upper() not in FUNCTIONS:
                return {"value": 0.0, "dependencies": deps, "trace": trace,
                        "errors": [f"unknown function {m.group(1)}"],
                        "error": f"unknown function {m.group(1)}", "warnings": warnings}
        # reject dangerous chars
        if re.search(r"[;{}\[\]\"'`$@#^&|!~\\]", expr.replace("!=","").replace(">=","").replace("<=","").replace("==","")):
            return {"value": 0.0, "dependencies": deps, "trace": trace,
                    "errors": ["disallowed characters"], "error": "disallowed characters",
                    "warnings": warnings}
        value = float(Parser(tokenize(expr), resolve).parse())
        if math.isinf(value) or math.isnan(value):
            warnings.append("result is non-finite (division by zero?)")
        trace.append(f"result={value}")
        return {"value": value, "dependencies": deps, "trace": trace,
                "errors": [], "error": None, "warnings": warnings}
    except Exception as e:
        return {"value": 0.0, "dependencies": deps, "trace": trace,
                "errors": [str(e)], "error": str(e), "warnings": warnings}

def dependencies_of(expr: str) -> list[str]:
    return extract_refs(expr)


def validate_expression(expr: str) -> dict:
    """Lightweight validation without a context. Returns {ok, dependencies, error}."""
    try:
        deps = extract_refs(expr)
        evaluate(expr, {})
        return {"ok": True, "dependencies": deps, "error": None}
    except Exception as e:
        try:
            deps = extract_refs(expr)
        except Exception:
            deps = []
        return {"ok": False, "dependencies": deps, "error": str(e)}
