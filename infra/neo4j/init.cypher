// Neo4j mirror for traversal (Postgres remains source of truth).
// Neo4j is an optional traversal mirror. Postgres remains the system of record.
// The application graph API (app/services/compiler.py) is written against the
// store interface, so this projection can be introduced without changing any
// application-level graph call.
CREATE CONSTRAINT node_id IF NOT EXISTS FOR (n:XNode) REQUIRE n.id IS UNIQUE;
CREATE INDEX edge_tenant IF NOT EXISTS FOR ()-[r:XREL]-() ON (r.tenant_id);
CREATE INDEX node_tenant IF NOT EXISTS FOR (n:XNode) ON (n.tenant_id);
