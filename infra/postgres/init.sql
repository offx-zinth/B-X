-- Business X-Ray schema. Postgres is the system of record for the graph.
-- The application also runs against an in-process store with the same
-- interface (app/core/store.py); this file is the durable production schema.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------- Identity / tenancy ----------
CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'Viewer'
    CHECK (role IN ('Owner','Admin','Analyst','Viewer')),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, email)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_global ON users(lower(email));

-- ---------- Ingestion ----------
CREATE TABLE IF NOT EXISTS data_sources (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'file',
  status TEXT NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED','PROCESSING','parsed','COMPLETED','FAILED','PARTIAL')),
  row_count INT DEFAULT 0,
  columns JSONB DEFAULT '[]',
  error TEXT,
  object_key TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sources_tenant ON data_sources(tenant_id);

-- ---------- Graph ----------
CREATE TABLE IF NOT EXISTS nodes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  properties JSONB NOT NULL DEFAULT '{}',
  state TEXT DEFAULT 'active',
  level TEXT NOT NULL DEFAULT 'INFERRED'
    CHECK (level IN ('CONFIRMED','INFERRED','USER_DEFINED','AI_SUGGESTED')),
  provenance JSONB NOT NULL DEFAULT '[]',
  source_docs JSONB NOT NULL DEFAULT '[]',
  confidence DOUBLE PRECISION DEFAULT 1.0,
  last_observed TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_nodes_tenant ON nodes(tenant_id);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(tenant_id, type);

CREATE TABLE IF NOT EXISTS edges (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  source_node UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  target_node UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  properties JSONB NOT NULL DEFAULT '{}',
  conditions JSONB NOT NULL DEFAULT '{}',
  formula TEXT,
  level TEXT NOT NULL DEFAULT 'INFERRED'
    CHECK (level IN ('CONFIRMED','INFERRED','USER_DEFINED','AI_SUGGESTED')),
  provenance JSONB NOT NULL DEFAULT '[]',
  source_docs JSONB NOT NULL DEFAULT '[]',
  confidence DOUBLE PRECISION DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_edges_tenant ON edges(tenant_id);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(tenant_id, source_node);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(tenant_id, target_node);

CREATE TABLE IF NOT EXISTS node_states (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  node_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  graph_version INT,
  state TEXT NOT NULL,
  state_data JSONB NOT NULL DEFAULT '{}',
  recorded_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_node_states ON node_states(tenant_id, node_id);

-- ---------- Formulas ----------
CREATE TABLE IF NOT EXISTS formulas (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  target TEXT NOT NULL,
  expression TEXT NOT NULL,
  dependencies JSONB NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','rejected','active')),
  level TEXT NOT NULL DEFAULT 'USER_DEFINED'
    CHECK (level IN ('CONFIRMED','INFERRED','USER_DEFINED','AI_SUGGESTED')),
  created_by TEXT DEFAULT 'user',
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_formulas_tenant ON formulas(tenant_id, status);

-- ---------- Versioning (immutable snapshots) ----------
CREATE TABLE IF NOT EXISTS graph_versions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  version INT NOT NULL,
  node_count INT DEFAULT 0,
  edge_count INT DEFAULT 0,
  formula_count INT DEFAULT 0,
  source TEXT,
  snapshot JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, version)
);

-- ---------- Simulation ----------
CREATE TABLE IF NOT EXISTS scenarios (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  base_graph_version INT,
  changes JSONB NOT NULL DEFAULT '[]',
  formula_overrides JSONB NOT NULL DEFAULT '[]',
  duration_days INT DEFAULT 14,
  status TEXT DEFAULT 'draft',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS simulation_runs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  scenario_id UUID REFERENCES scenarios(id) ON DELETE CASCADE,
  base_graph_version INT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','running','done','failed')),
  duration_ms INT DEFAULT 0,
  results JSONB NOT NULL DEFAULT '{}',
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_runs_tenant ON simulation_runs(tenant_id, created_at DESC);

-- ---------- Audit ----------
CREATE TABLE IF NOT EXISTS audit_log (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id TEXT,
  email TEXT,
  action TEXT NOT NULL,
  resource TEXT,
  before JSONB DEFAULT '{}',
  after JSONB DEFAULT '{}',
  metadata JSONB DEFAULT '{}',
  timestamp TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS reports (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  report JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ---------- Application role ----------
-- The POSTGRES_USER is a SUPERUSER, and superusers bypass RLS even with
-- FORCE. The API therefore connects as a dedicated non-superuser role so
-- Row Level Security is genuinely enforced, not merely declared.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'xray_app') THEN
    CREATE ROLE xray_app LOGIN PASSWORD 'xrayapp'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;

GRANT CONNECT ON DATABASE xray TO xray_app;
GRANT USAGE, CREATE ON SCHEMA public TO xray_app;
-- The app role must own the tables so it can manage them (and so RLS
-- FORCE applies to the connecting role rather than a superuser).
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['tenants','users','data_sources','nodes','edges','node_states',
                           'formulas','graph_versions','scenarios','simulation_runs',
                           'audit_log','reports']
  LOOP
    EXECUTE format('ALTER TABLE %I OWNER TO xray_app', t);
  END LOOP;
END $$;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO xray_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO xray_app;

-- ---------- Row Level Security ----------
-- The API already filters on tenant_id from the JWT (app/core/tenant.py).
-- RLS is defence in depth: the app sets app.tenant_id per transaction so a
-- missed filter cannot leak another tenant's graph.
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['nodes','edges','formulas','data_sources','graph_versions',
                           'scenarios','simulation_runs','audit_log','reports',
                           'node_states','users']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I '
      'USING (current_setting(''app.tenant_id'', true) = ''all'' '
      'OR (NULLIF(current_setting(''app.tenant_id'', true), '''') IS NOT NULL '
      'AND tenant_id::text = current_setting(''app.tenant_id'', true)))', t);
  END LOOP;
END $$;