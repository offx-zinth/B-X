"""Baseline: normalized schema is managed by init.sql; this revision only adds
the enterprise deltas (outbox + transitional indexes) idempotently."""

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    import sqlalchemy as sa
    op.execute(sa.text("""
    CREATE TABLE IF NOT EXISTS outbox_events (
      id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      tenant_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      payload JSONB NOT NULL DEFAULT '{}',
      created_at TIMESTAMPTZ DEFAULT now(),
      claimed_at TIMESTAMPTZ,
      done_at TIMESTAMPTZ
    );
    CREATE INDEX IF NOT EXISTS idx_outbox_claim ON outbox_events (claimed_at, done_at, created_at);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_formulas_tenant_target ON formulas (tenant_id, target)
      WHERE status = 'approved';
    CREATE INDEX IF NOT EXISTS idx_xray_users_email ON xray_store ((lower(data->>'email')))
      WHERE collection = 'users';
    """))


def downgrade() -> None:
    from alembic import op
    import sqlalchemy as sa
    op.execute(sa.text("DROP TABLE IF EXISTS outbox_events"))
