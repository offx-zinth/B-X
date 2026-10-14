"""Live end-to-end AI check against the real Gemini API.

Run manually (needs a key); not part of the default suite.
  GEMINI_API_KEY=... python3.11 apps/api/tests/live_ai_check.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core import store
from app.core.store import clear
from app.services import llm
from app.services.ai import agent, tools
from app.services import formula_engine as bfl
from app.services import seed as sv

KEY = os.environ.get("GEMINI_API_KEY", "")
if not KEY:
    print("SKIP: GEMINI_API_KEY not set")
    sys.exit(0)

clear()
ctx = {"tenant_id": "11111111-1111-1111-1111-111111111111", "user_id": "u1", "email": "a@x.co"}
store.insert("tenants", ctx, {"id": ctx["tenant_id"], "name": "Acme"})
store.insert("users", ctx, {"id": "u1", "email": "a@x.co", "role": "Owner"})
now = datetime.now().isoformat()
ids = {}
for t, name, props in sv.NODES:
    n = store.insert("nodes", ctx, {"type": t, "name": name, "properties": dict(props),
                                   "state": "active", "confidence": 0.95, "level": "CONFIRMED",
                                   "source_docs": ["demo seed"], "last_observed": now})
    ids[t] = n["id"]
for s, t, typ in sv.EDGES:
    store.insert("edges", ctx, {"source_node": ids[s], "target_node": ids[t], "type": typ,
                                "properties": {}})
for target, expr in sv.FORMULAS:
    store.insert("formulas", ctx, {"target": target, "expression": expr,
                                   "dependencies": bfl.dependencies_of(expr),
                                   "status": "approved", "created_by": "seed", "level": "CONFIRMED"})

print("provider status:", llm.status())
print("schema problems:", tools.validate_schemas() or "none")
print()

QUESTIONS = [
    "What happens if we lose our largest supplier?",
    "Which nodes are bottlenecks and why?",
    "What is our current revenue and backlog?",
    "How would we reduce delivery delays under a 5% cost increase?",
    "What is the airspeed velocity of a swallow in Patagonia?",
]

for q in QUESTIONS:
    res = agent.ask(ctx, q)
    print("=" * 78)
    print("Q:", q)
    print("provider:", res["provider"], "| model:", res["model"])
    print("tools   :", ", ".join(res["steps"]) or "(none)")
    print("grounded:", res["grounding"]["fully_grounded"],
          "| ungrounded:", res["grounding"]["ungrounded_refs"] or "none")
    if res["error"]:
        print("error   :", res["error"][:200])
    print("answer  :", res["answer"][:700].replace("\n", " "))
    print()
