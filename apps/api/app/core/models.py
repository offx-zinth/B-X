"""SQLAlchemy 2.0 models mirroring infra/postgres/init.sql.

The xray_store JSONB table remains the compat backend until the Alembic
cutover completes. New code should import these models for typed access;
the outbox table enables the Neo4j mirror worker without dual writes.
"""
from __future__ import annotations
import uuid
from sqlalchemy import Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, default="Viewer", nullable=False)


class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    level: Mapped[str] = mapped_column(Text, default="INFERRED", nullable=False)


class Edge(Base):
    __tablename__ = "edges"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    source_node: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    target_node: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    formula: Mapped[str | None] = mapped_column(Text)


class Formula(Base):
    __tablename__ = "formulas"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)


class OutboxEvent(Base):
    """Transactional outbox for the Neo4j mirror worker.

    Writers insert inside the same transaction as the graph mutation; a
    lightweight worker claims rows (claimed_at IS NULL ... FOR UPDATE SKIP
    LOCKED), mirrors to Neo4j, then marks them done. Deployments without
    Neo4j simply leave the worker scaled to 0 — Postgres stays source of truth.
    """
    __tablename__ = "outbox_events"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # node.upsert | edge.upsert | ...
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claimed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
