"""baseline schema

Revision ID: 20260329_0001
Revises:
Create Date: 2026-03-29 00:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.extensions import db
import app.models  # noqa: F401

# revision identifiers, used by Alembic.
revision = "20260329_0001"
down_revision = None
branch_labels = None
depends_on = None


LEGACY_MIGRATIONS = (
    ("0001", "create base schema"),
    ("0002", "add product publishing columns"),
    ("0003", "add shops and backfill shop stock"),
    ("0004", "add shop-aware sales columns"),
)


def _ensure_legacy_schema_migrations(bind) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table("schema_migrations"):
        op.create_table(
            "schema_migrations",
            sa.Column("version", sa.String(length=64), primary_key=True),
            sa.Column("description", sa.String(length=255), nullable=False),
            sa.Column("applied_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    for version, description in LEGACY_MIGRATIONS:
        existing = bind.execute(
            sa.text("SELECT 1 FROM schema_migrations WHERE version = :version"),
            {"version": version},
        ).fetchone()
        if existing:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO schema_migrations (version, description)
                VALUES (:version, :description)
                """
            ),
            {"version": version, "description": description},
        )


def upgrade():
    bind = op.get_bind()
    db.metadata.create_all(bind=bind)
    _ensure_legacy_schema_migrations(bind)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("schema_migrations"):
        op.drop_table("schema_migrations")
    db.metadata.drop_all(bind=bind)
