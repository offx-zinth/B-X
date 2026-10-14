# Business X-Ray — Executable Business Operating Graph

> The graph is the source of truth. The LLM is an orchestration and
> interpretation layer, never the source of business state.

```
RAW BUSINESS REALITY → DISCOVERY → BUSINESS IR → GRAPH COMPILER
→ EXECUTABLE DIGITAL TWIN → SIMULATION → DECISION INTELLIGENCE
```

Remove the AI layer and the graph, formula engine, dependency resolver and
simulation engine still work correctly. That separation is the product.

## Stack

- **Frontend** — Next.js 14, TypeScript, Tailwind, React Flow–style custom SVG
  canvas, Phosphor icons. Server-rendered shell, client-side data fetching.
- **Backend** — Python 3.11, FastAPI, Pydantic v2.
- **Store** — durable JSONB document store in Postgres with an identical
  in-process interface (so unit tests and offline runs need no DB). The graph
  abstraction sits behind `app/core/store.py`, so Postgres/Neo4j can be swapped
  without touching application code.
- **Auth** — JWT with mandatory `tenant_id`; RBAC (Owner/Admin/Analyst/Viewer)
  enforced server-side.
- **Observability** — structured JSON logs, request IDs, in-process metrics,
  `/health`, `/ready`, `/metrics`.

## Setup

### Requirements

- **Python 3.11+** (the API and tests)
- **Node.js 20+** (the web app)
- **Docker** (Postgres 16; optional Neo4j traversal mirror)
- A **Gemini API key** for the live AI — optional. Without it the copilot runs
  the deterministic engine over the same tools: still correct, just not
  conversational.

### One command

```bash
git clone https://github.com/offx-zinth/B-X.git
cd B-X
cp .env.example .env        # optional: add GEMINI_API_KEY
./start.sh
```

`start.sh` brings up Postgres, applies the schema, creates the RLS-enforcing
app role, starts the API and web, waits for health checks, and seeds a demo
tenant with the reference supplier-failure scenario.

```
Web        http://localhost:3000
API docs   http://localhost:8000/docs
Login      demo@acme.co / secret123
```

`start.sh` commands:

| Command | Effect |
| --- | --- |
| `./start.sh` | Start everything and seed the demo |
| `./start.sh --status` | Show processes, containers and health |
| `./start.sh --logs` | Tail API and web logs (in `.run/`) |
| `./start.sh --stop` | Stop all services |
| `./start.sh --reset` | Drop the database volume and start fresh |
| `./start.sh --docker` | Force the full Docker path (slower first build) |
| `./start.sh --native` | Force the native path |

### Manual setup

<details>
<summary>Run the pieces yourself</summary>

**1. Postgres** — and the non-superuser app role. The `POSTGRES_USER` is a
superuser, and superusers bypass Row Level Security, so the API must connect as
a dedicated role for tenant isolation to actually be enforced.

```bash
docker compose up -d postgres
until docker exec business-xray-postgres-1 pg_isready -U xray -d xray; do sleep 2; done

docker exec business-xray-postgres-1 psql -U xray -d xray -q \
  -c "CREATE ROLE xray_app LOGIN PASSWORD 'xrayapp' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS" \
  -c "GRANT CONNECT ON DATABASE xray TO xray_app" \
  -c "GRANT USAGE, CREATE ON SCHEMA public TO xray_app" \
  -c "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO xray_app"
```

`./start.sh` does this for you. `infra/postgres/init.sql` also provisions the
role and table ownership on a fresh volume.

**2. API**

```bash
cd apps/api
pip install -r requirements.txt
export DATABASE_URL="postgresql://xray_app:xrayapp@localhost:5432/xray"
export JWT_SECRET="change-me"
export GEMINI_API_KEY="..." LLM_PROVIDER=gemini LLM_MODEL=gemma-4-31b-it
uvicorn app.main:app --reload --port 8000
```

**3. Web**

```bash
cd apps/web
npm install
npm run build && npm run start     # or: npm run dev
```

</details>

### Configuration

All configuration is environment-based (see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | Enables the live LLM. Absent → deterministic mode |
| `LLM_PROVIDER` | `gemini` | `gemini` / `openai` / anything else → offline |
| `LLM_MODEL` | `gemma-4-31b-it` | Any model the provider serves |
| `DATABASE_URL` | local `xray_app` | **Must not** be the Postgres superuser |
| `JWT_SECRET` | dev value | Change for any real deployment |
| `API_PORT` / `WEB_PORT` | `8000` / `3000` | Service ports |

### Verify the install

```bash
python3.11 -m pytest apps/api/tests -q     # 54 unit/integration tests
python3.11 apps/api/tests/e2e_dod.py       # 21-step Definition-of-Done run
./scripts/smoke.sh                         # 28 live checks against the running app
```

With a live Postgres the RLS suite also runs:

```bash
XRAY_TEST_PG="postgresql://xray_app:xrayapp@localhost:5432/xray" \
  python3.11 -m pytest apps/api/tests -q    # 60 tests incl. tenant-isolation proofs
```

To exercise the live LLM by hand:

```bash
GEMINI_API_KEY=... python3.11 apps/api/tests/live_ai_check.py
```

---


## Architecture

Modular monolith, clean seams, no premature microservices. Every module is
independent and can be extracted to a service when scale demands it.

```
apps/api/app/
  core/        store (Postgres+memory), tenant guard, security/JWT, roles (RBAC),
               audit, versions (immutable graph snapshots), observability
  services/    ingestion → ir (discovery + normalization) → compiler (IR→graph)
               formula_engine (BFL) → simulation (layered solver) → ai_orchestrator
               provenance, seed
  routers/     auth, ingest, graph, formulas, simulations, ai, dashboard,
               reports, system
```

## The engines (all deterministic, all tested)

### Formula engine (BFL)
A controlled expression language — **no arbitrary Python/JS is ever executed**.
Recursive-descent parser over a whitelist: `SUM AVG MIN MAX IF ABS ROUND COUNT
RATE DELTA CLAMP`. References are `Type.property` (and `prev.Type.property` for
cross-day stocks). Missing refs resolve to `0.0` with an explicit warning —
values are never invented. Returns `{value, dependencies, trace, errors,
warnings}`. Grammar: `packages/bfl/README.md`.

### Dependency + simulation engine
Formulas split into **flow** (topologically ordered, converge in one pass) and
**stock** (self-referential via `prev.`, read the previous day's close). This
avoids the oscillation a naive fixpoint loop produces on self-referential
inventory. Baseline and scenario run through the *same* solver, so a comparison
can never diverge due to different evaluation logic. Simulations never mutate
live state — they run on a deep copy, record a daily `t0..tn` timeline, and
return absolute + percentage change, time-to-impact, and maximum impact.

### Graph service
`get_node · update_node · create_node · get_neighbors · get_dependencies ·
get_dependents · trace_path · find_affected_nodes · find_upstream ·
find_downstream · dependency_closure`, plus immutable graph versioning. Every
mutation snapshots a new version; simulations pin a `base_graph_version`.

## AI layer — tools, not chat

The copilot is a real tool-calling agent over 18 audited, tenant-scoped tools
(`query_graph`, `find_dependencies`, `explain_simulation`, `run_simulation`,
`get_metric`, `find_bottlenecks`, `suggest_optimization`, …). It is not a chat
wrapper: the model can only learn facts by calling tools, and every call is
written to the audit log.

**Provider-agnostic by construction.** Application code never imports a vendor
SDK — it talks to `LLMClient` (`app/services/llm/base.py`). Providers are
selected purely by environment:

| Env | Meaning |
| --- | --- |
| `LLM_PROVIDER` | `gemini` (default) / `openai` / anything else => offline |
| `LLM_MODEL` | e.g. `gemma-4-31b-it`, served through the Gemini API |
| `GEMINI_API_KEY` / `LLM_API_KEY` | credential; absent => deterministic mode |

```bash
export GEMINI_API_KEY=... LLM_PROVIDER=gemini LLM_MODEL=gemma-4-31b-it
curl localhost:8000/ai/status     # which provider/model is live
curl localhost:8000/ai/models     # models the provider exposes
```

**Guardrails (each is tested):**
- **Grounding** — every `Type.property` the answer cites is checked against tool
  results *and* the supplied context. Ungrounded citations are stripped and
  reported, so the model cannot invent graph facts.
- **No self-computation** — computed metrics are read via `get_metric`, never
  derived by the model doing arithmetic on formula inputs.
- **Bounded context** — only a relevance-ranked slice of the graph is sent.
- **Approval gate** — `create_formula` always returns a `pending` proposal
  (`AI_SUGGESTED`); scenarios are created as drafts. Nothing auto-applies.
- **Deterministic floor** — with no credential, or if the provider errors, the
  deterministic client answers from the same tools. The product stays a valid
  simulation platform with the LLM removed, and degradation is reported
  explicitly (`degraded`, `error`) rather than hidden.
- **Robustness** — duplicate tool calls are suppressed; transient 429/5xx back
  off and retry before degrading; tool JSON schemas are validated for
  cross-provider portability.


## Data, provenance, normalization
Upload CSV/XLSX/JSON/PDF/DOCX through a status-tracked pipeline
(`QUEUED → PROCESSING → COMPLETED/FAILED/PARTIAL`; failures are retained and
inspectable). Heterogeneous columns are normalized onto canonical business
properties (`capacity_kg → capacity`, `lead_time_days → lead_time`,
`available_kg → available`) so separate exports compile into one executable
graph. Every fact carries provenance and a lifecycle level —
`CONFIRMED · INFERRED · USER_DEFINED · AI_SUGGESTED`. Inferred data is never
presented as confirmed.

## Reference scenario (Acme Manufacturing)
`Supplier.capacity=0 for 14 days` propagates deterministically through
`Supplier → Material → Production → Order → Revenue`: production capacity
collapses to 0, fulfillable orders to 0, backlog rises to full demand, revenue
to 0 — and the copilot explains what changed, which nodes were affected, when,
why (citing the exact formula), which metrics moved, the binding constraint,
and candidate interventions. Locked in by
`apps/api/tests/test_reference_scenario.py`.

## What is deliberately not faked
Ingestion, IR discovery, graph compilation, formula evaluation, dependency
propagation, simulation, impact analysis, versioning, RBAC, audit and every AI
tool hit the real backend. The only thing removed if you disable the LLM is the
optional provider hook; the deterministic engine is self-sufficient.
