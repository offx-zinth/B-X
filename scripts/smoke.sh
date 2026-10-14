#!/usr/bin/env bash
# Live smoke test against the running docker-compose stack.
# Usage: ./scripts/smoke.sh [API_URL]
set -uo pipefail
API="${1:-http://localhost:8000}"
pass=0; fail=0
check() { # name, expected_substring, actual
  if has "$3" "$2"; then echo "PASS  $1"; pass=$((pass+1));
  else echo "FAIL  $1  (expected '$2' in: ${3:0:200})"; fail=$((fail+1)); fi
}
j() { python3 -c "import sys,json;d=json.load(sys.stdin);print(eval('d'+sys.argv[1]))" "$1" 2>/dev/null | tr -d '\n'; }
# normalized comparison: collapse whitespace so JSON spacing never fails a check
n() { python3 -c "import sys;print(sys.stdin.read().replace(' ','').replace(chr(10),''))"; }
has() { [[ "$(printf '%s' "$1" | n)" == *"$(printf '%s' "$2" | n)"* ]]; }

echo "=== Business X-Ray live smoke test ==="
STAMP=$(date +%s%N)
check "api health"        '"ok":true'   "$(curl -s $API/health)"
check "readiness"         '"ready":true' "$(curl -s $API/ready)"
check "api v1 mirror"     '"api":"v1"'  "$(curl -s $API/api/v1/health)"

# 1. create org
R=$(curl -s -X POST $API/auth/signup -H 'Content-Type: application/json' \
    -d "{\"org\":\"Smoke Co\",\"email\":\"smoke-$STAMP@x.co\",\"password\":\"secret123\"}")
TOK=$(echo "$R" | j "['token']"); TID=$(echo "$R" | j "['tenant_id']")
check "signup returns tenant+token" "tenant_id" "$R"
H="Authorization: Bearer $TOK"
check "auth me"           '"role":"Owner"' "$(curl -s $API/auth/me -H "$H")"

# 2. seed the Acme reference graph
S=$(curl -s -X POST $API/ingest/seed -H "$H")
check "seed executable graph" '"seeded":true' "$S"

# 3. graph
N=$(curl -s $API/graph/nodes -H "$H"); E=$(curl -s $API/graph/edges -H "$H")
check "graph nodes"       '"ABC Metals"' "$N"
check "graph edges"       'supplies'      "$E"
check "graph versions"    '"version"'     "$(curl -s $API/graph/versions -H "$H")"

# 4. formulas approved
check "approved formulas" '"approved"' "$(curl -s $API/formulas/ -H "$H")"

# 5. impact analysis (re-fetch nodes after seeding so the id is current)
N=$(curl -s $API/graph/nodes -H "$H")
SID=$(echo "$N" | python3 -c "import sys,json;d=json.load(sys.stdin);print(next(n['id'] for n in d if n['type']=='Supplier'))")
check "impact analysis"   'affected_count' "$(curl -s $API/graph/impact/$SID -H "$H")"
check "impact upstream"   'upstream_count' "$(curl -s $API/graph/impact/$SID -H "$H")"

# 6. simulation: supplier failure
SIM=$(curl -s -X POST $API/simulations/run -H "$H" -H 'Content-Type: application/json' \
  -d '{"name":"Supplier ABC capacity = 0","changes":[{"target":"Supplier.capacity","value":0}],"duration_days":14}')
check "simulation ran"     '"status":"done"' "$SIM"
check "production -> 0"    '"Production.capacity":{"before":500.0,"after":0.0' "$SIM"
check "revenue collapsed"  '"Revenue.total":{"before":60000.0,"after":0.0' "$SIM"
check "14-day timeline"    'timeline'        "$SIM"

# 7. AI copilot explanation
AI=$(curl -s -X POST $API/ai/ask -H "$H" -H 'Content-Type: application/json' \
  -d '{"question":"What happens if we lose our largest supplier?"}')
check "AI explains why"    'binding constraint' "$AI"
check "AI lists metrics"   'Revenue.total'      "$AI"

# 8. AI tool layer
check "ai tool: bottlenecks"  'bottlenecks' "$(curl -s -X POST $API/ai/tools/find_bottlenecks -H "$H" -H 'Content-Type: application/json' -d '{"args":{}}')"
check "ai tool: risks"        'risks'       "$(curl -s -X POST $API/ai/tools/find_risks -H "$H" -H 'Content-Type: application/json' -d '{"args":{}}')"
check "ai tool: metric"       'available'   "$(curl -s -X POST $API/ai/tools/get_metric -H "$H" -H 'Content-Type: application/json' -d '{"args":{"ref":"Supplier.capacity"}}')"

# 9. dashboard + reports + optimization
check "dashboard"          'model_confidence' "$(curl -s $API/dashboard/ -H "$H")"
check "report"             'executive_summary' "$(curl -s $API/reports/ -H "$H")"
check "report csv export"  'section,key,value' "$(curl -s $API/reports/export.csv -H "$H")"
check "optimization"       'recommended'       "$(curl -s -X POST $API/ai/optimize -H "$H" -H 'Content-Type: application/json' -d '{"question":"reduce delivery delays under 5% cost"}')"

# 10. audit trail
check "audit log"          'ingest.seed' "$(curl -s $API/audit -H "$H")"

# 11. tenant isolation: second org must not see the first graph
R2=$(curl -s -X POST $API/auth/signup -H 'Content-Type: application/json' \
     -d "{\"org\":\"Other Co\",\"email\":\"other-$STAMP@x.co\",\"password\":\"secret123\"}")
TOK2=$(echo "$R2" | j "['token']")
check "tenant isolation"   '[]' "$(curl -s $API/graph/nodes -H "Authorization: Bearer $TOK2")"

# 12. web is up
check "web frontend"       'Business X-Ray' "$(curl -s http://localhost:3000)"

echo
echo "=== $pass passed, $fail failed ==="
[[ $fail -eq 0 ]]
