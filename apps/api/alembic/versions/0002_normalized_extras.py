"""0002: normalized extras — ingest_jobs, pgvector embeddings, ltree paths.

Everything is idempotent and degrades gracefully when an extension is not
available on the target Postgres (managed RDS without pgvector, etc.).
"""

revision = "0002_normalized_extras"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    import sqlalchemy as sa
    op.execute(sa.text("""
    CREATE TABLE IF NOT EXISTS ingest_jobs (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      kind TEXT,
      filename TEXT,
      size BIGINT,
      status TEXT,
      queue TEXT,
      progress INT DEFAULT 0,
      error TEXT,
      result JSONB,
      created_at TIMESTAMPTZ DEFAULT now(),
      updated_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_ingest_jobs_tenant ON ingest_jobs(tenant_id, created_at DESC);

    DO $$
    BEGIN
      CREATE EXTENSION IF NOT EXISTS vector;
      CREATE TABLE IF NOT EXISTS node_embeddings (
        tenant_id TEXT NOT NULL,
        node_id UUID NOT NULL,
        content_hash TEXT NOT NULL,
        embedding vector(256) NOT NULL,
        PRIMARY KEY (tenant_id, node_id)
      );
      BEGIN
        CREATE INDEX IF NOT EXISTS idx_node_embeddings_ivfflat
          ON node_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
      EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'ivfflat index skipped: %', SQLERRM;
      END;
    EXCEPTION WHEN OTHERS THEN
      RAISE NOTICE 'pgvector unavailable, semantic search falls back to in-memory index';
    END $$;

    DO $$
    BEGIN
      CREATE EXTENSION IF NOT EXISTS ltree;
      CREATE TABLE IF NOT EXISTS node_paths (
        tenant_id UUID NOT NULL,
        node_id UUID PRIMARY KEY,
        path ltree NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_node_paths_gist ON node_paths USING GIST (path);
    EXCEPTION WHEN OTHERS THEN
      RAISE NOTICE 'ltree unavailable, deep-hierarchy prefix cache disabled';
    END $$;
    """))


def downgrade() -> None:
    from alembic import op
    import sqlalchemy as sa
    op.execute(sa.text("""
    DROP TABLE IF EXISTS node_embeddings;
    DROP TABLE IF EXISTS node_paths;
    DROP TABLE IF EXISTS ingest_jobs;
    """))
