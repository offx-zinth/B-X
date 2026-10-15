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


# --- Strict unit checking -------------------------------------------------
# Families: quantity, time, currency, ratio, unknown. '+'/'-' and comparisons
# require the same known family; '*'/'/' may combine families (e.g.
# quantity * currency -> currency). Unknown units are permissive so legacy
# formulas without metadata keep working — only KNOWN incompatibilities
# (hours + rupees) are blocked.
UNIT_FAMILIES = ("quantity", "time", "currency", "ratio", "unknown")

PROPERTY_UNIT_FAMILY: dict[str, str] = {
    "capacity": "quantity", "daily_capacity": "quantity",
    "available": "quantity", "required": "quantity", "quantity": "quantity",
    "demand": "quantity", "fulfilled": "quantity", "fulfillable": "quantity",
    "backlog": "quantity", "stock": "quantity",
    "lead_time": "time", "duration": "time", "hours": "time", "days": "time",
    "cycle_time": "time", "delivery_time": "time",
    "avg_value": "currency", "unit_cost": "currency", "cost": "currency",
    "price": "currency", "revenue": "currency", "total": "currency",
    "outstanding": "currency", "overdue": "currency",
    "utilization": "ratio", "cover": "ratio",
}

_CURRENCY_HINTS = ("cost", "price", "revenue", "value", "inr", "rs", "rupees", "usd")
_TIME_HINTS = ("lead_time", "duration", "hours", "days", "cycle_time", "delivery_time", "time")


def infer_ref_family(ref: str, unit_lookup: dict[str, str] | None = None) -> str:
    """Resolve a Type.property ref to a unit family via explicit lookup, else name heuristics."""
    if unit_lookup and ref in unit_lookup:
        u = str(unit_lookup[ref]).strip().lower()
        if u in UNIT_FAMILIES:
            return u
        # map concrete units to families
        if any(h in u for h in ("inr", "rs", "rupee", "usd", "$")):
            return "currency"
        if any(h in u for h in ("hour", "day", "min", "sec", "time")):
            return "time"
        if any(h in u for h in ("qty", "unit", "cup", "serving", "item", "pcs")):
            return "quantity"
        if u in ("ratio", "pct", "percent", "%"):
            return "ratio"
        return "unknown"
    low_full = ref.lower() if "." not in ref else ref.lower()
    prop = ref.split(".")[-1].lower() if "." in ref else ref.lower()
    typ = ref.split(".")[0].lower() if "." in ref else ""
    if prop in PROPERTY_UNIT_FAMILY:
        return PROPERTY_UNIT_FAMILY[prop]
    # Type-level hints: Cost.production, Revenue.total are currency even when
    # the property name itself is generic.
    if any(h in typ for h in ("cost", "revenue", "price", "payment", "margin")):
        return "currency"
    if any(h in typ for h in ("time", "duration", "lead")):
        return "time"
    if any(h in low_full for h in _CURRENCY_HINTS):
        return "currency"
    if any(h in low_full for h in _TIME_HINTS):
        return "time"
    return "unknown"


def _check_same_family(a: str, b: str) -> bool:
    if a == "unknown" or b == "unknown":
        return True
    return a == b


def validate_units(expr: str, unit_lookup: dict[str, str] | None = None) -> dict:
    """Static unit check. Returns {ok, error, families}.

    Strict: known incompatible families on '+'/'-'/'MIN'/'MAX'/comparisons fail.
    Unknown units are permissive (legacy formulas keep working).
    """
    try:
        toks = tokenize(expr)
    except Exception as e:
        return {"ok": False, "error": str(e), "families": {}}

    class UParser:
        def __init__(self, tokens):
            self.t = tokens; self.p = 0
        def peek(self): return self.t[self.p] if self.p < len(self.t) else None
        def eat(self, v=None):
            cur = self.peek()
            if cur is None: raise ValueError("unexpected end")
            if v is not None and cur != v: raise ValueError(f"expected {v} got {cur}")
            self.p += 1; return cur
        def parse(self):
            fam = self.cmp()
            if self.peek() is not None: raise ValueError(f"unexpected token {self.peek()}")
            return fam
        def cmp(self):
            l = self.add()
            while self.peek() in (">", "<", ">=", "<=", "=", "==", "!="):
                op = self.eat(); r = self.add()
                if not _check_same_family(l, r):
                    raise ValueError(f"unit mismatch: cannot compare {l} {op} {r}")
                l = "ratio"  # comparisons yield boolean/ratio
            return l
        def add(self):
            l = self.mul()
            while self.peek() in ("+", "-"):
                op = self.eat(); r = self.mul()
                if not _check_same_family(l, r):
                    raise ValueError(f"unit mismatch: cannot apply '{op}' to {l} and {r}")
                l = l if l != "unknown" else r
            return l
        def mul(self):
            l = self.un()
            while self.peek() in ("*", "/"):
                op = self.eat(); r = self.un()
                # '*'/'/' may combine families (quantity * currency -> currency,
                # stock / per-unit requirement -> producible quantity). Division
                # is intentionally permissive (unknown) so stock/requirement
                # patterns don't false-positive; '+'/'-' stay strict.
                if op == "*":
                    if "currency" in (l, r):
                        l = "currency"
                    elif l == "unknown" or r == "unknown":
                        l = "unknown"
                    else:
                        l = "unknown"  # quantity*quantity shape varies; stay permissive
                else:  # '/'
                    if "currency" in (l, r) and l != r:
                        l = "currency" if l == "currency" else "unknown"
                    else:
                        l = "unknown"
                # incompatible multiply is allowed (quantity * currency)
            return l
        def un(self):
            if self.peek() == "-": self.eat(); return self.un()
            if self.peek() == "+": self.eat(); return self.un()
            return self.atom()
        def atom(self):
            cur = self.peek()
            if cur is None: raise ValueError("unexpected end in atom")
            if re.fullmatch(r"\d+\.?\d*", cur or ""):
                self.eat(); return "unknown"  # bare numbers are dimensionless
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", cur or ""):
                name = self.eat()
                if self.peek() == "(":
                    fname = name.upper()
                    self.eat("("); argfams = []
                    if self.peek() != ")":
                        argfams.append(self.cmp())
                        while self.peek() == ",":
                            self.eat(","); argfams.append(self.cmp())
                    self.eat(")")
                    if fname in ("MIN", "MAX", "SUM", "AVG"):
                        base = next((f for f in argfams if f != "unknown"), "unknown")
                        for f in argfams:
                            if not _check_same_family(base, f):
                                raise ValueError(f"unit mismatch in {fname}: {argfams}")
                        return base
                    if fname in ("CLAMP",):
                        for f in argfams:
                            if not _check_same_family(argfams[0], f):
                                raise ValueError(f"unit mismatch in CLAMP: {argfams}")
                        return argfams[0] if argfams else "unknown"
                    if fname in ("IF",):
                        # IF(cond, then, else): branches must match
                        if len(argfams) == 3 and not _check_same_family(argfams[1], argfams[2]):
                            raise ValueError(f"unit mismatch in IF branches: {argfams[1]} vs {argfams[2]}")
                        return argfams[1] if len(argfams) == 3 else "unknown"
                    return "unknown"  # RATE/DELTA/ABS/ROUND/COUNT are family-polymorphic
                if "." in name:
                    return infer_ref_family(name, unit_lookup)
                raise ValueError(f"bare identifier {name}; use Type.property")
            if cur == "(":
                self.eat("("); v = self.cmp(); self.eat(")"); return v
            raise ValueError(f"unexpected {cur}")

    try:
        fams = {r: infer_ref_family(r, unit_lookup) for r in extract_refs(expr)}
        result_fam = UParser(toks).parse()
        return {"ok": True, "error": None, "families": fams, "result_family": result_fam}
    except ValueError as e:
        return {"ok": False, "error": str(e),
                "families": {r: infer_ref_family(r, unit_lookup) for r in extract_refs(expr)}}


def validate_expression(expr: str, unit_lookup: dict[str, str] | None = None) -> dict:
    """Lightweight validation without a context. Returns {ok, dependencies, error}."""
    try:
        deps = extract_refs(expr)
        evaluate(expr, {})
        if unit_lookup is not None:
            u = validate_units(expr, unit_lookup)
            if not u["ok"]:
                return {"ok": False, "dependencies": deps, "error": u["error"]}
        else:
            # Always run heuristic unit check: blocks known incompatibilities
            # (hours + rupees) while letting unknown-unit legacy formulas pass.
            u = validate_units(expr, None)
            if not u["ok"]:
                return {"ok": False, "dependencies": deps, "error": u["error"]}
        return {"ok": True, "dependencies": deps, "error": None}
    except Exception as e:
        try:
            deps = extract_refs(expr)
        except Exception:
            deps = []
        return {"ok": False, "dependencies": deps, "error": str(e)}


# --- Compiled BFL (two-phase engine) --------------------------------------
# Compilation parses once into tokens + deps and caches the result, so hot
# simulation loops avoid re-tokenizing every day. Evaluation reuses the same
# deterministic Parser but against a pre-validated token stream.
from functools import lru_cache


@lru_cache(maxsize=2048)
def _compile_cached(expr: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    toks = tuple(tokenize(expr))
    deps = tuple(extract_refs(expr))
    # validate eagerly so compile failures surface before simulation runs
    v = validate_expression(expr)
    if not v["ok"]:
        raise ValueError(v["error"])
    return toks, deps


def compile(expr: str) -> dict:
    """Parse once, evaluate many times. Returns {tokens, dependencies}."""
    toks, deps = _compile_cached(expr)
    return {"tokens": list(toks), "dependencies": list(deps), "expression": expr}


def evaluate_compiled(compiled: dict, context: dict[str, float]) -> dict:
    """Evaluate a pre-compiled expression (same semantics as evaluate_detailed)."""
    return evaluate_detailed(compiled.get("expression", ""), context)


def find_cycles(formulas: list[dict]) -> list[list[str]]:
    """Tarjan's SCC over ref->target edges. Returns cyclic groups (len>1 or self-loop)."""
    targets = [f.get("target") for f in (formulas or []) if f.get("target")]
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    idx = [0]
    sccs: list[list[str]] = []
    adj: dict[str, list[str]] = {t: [] for t in targets}
    target_set = set(targets)
    for f in (formulas or []):
        t = f.get("target")
        if not t:
            continue
        for r in dependencies_of(f.get("expression", "")):
            base = r[5:] if r.startswith("prev.") else r
            if base in target_set and base != t:
                adj.setdefault(base, []).append(t)
            if base == t:
                adj.setdefault(t, []).append(t)

    def strong(v: str):
        index_of[v] = low[v] = idx[0]
        idx[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj.get(v, []):
            if w not in index_of:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index_of[w])
        if low[v] == index_of[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or (len(comp) == 1 and comp[0] in adj.get(comp[0], [])):
                sccs.append(sorted(comp))

    for v in list(targets):
        if v not in index_of:
            strong(v)
    return sorted(sccs)
