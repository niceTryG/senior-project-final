from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text

from .db_patch import (
    _log_db_info,
    patch_products_columns,
    patch_sales_table,
    patch_shops_and_shop_stock,
)
from .extensions import db


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    apply: Callable[[], None]


def _ensure_migration_table() -> None:
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(64) PRIMARY KEY,
                description VARCHAR(255) NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.session.commit()


def _applied_versions() -> set[str]:
    _ensure_migration_table()
    rows = db.session.execute(
        text("SELECT version FROM schema_migrations ORDER BY version")
    ).fetchall()
    return {str(version) for (version,) in rows}


def _record_migration(migration: Migration) -> None:
    db.session.execute(
        text(
            """
            INSERT INTO schema_migrations (version, description)
            VALUES (:version, :description)
            """
        ),
        {
            "version": migration.version,
            "description": migration.description,
        },
    )
    db.session.commit()


def _migration_0001_initial_schema() -> None:
    db.create_all()


def _migration_0002_products_columns() -> None:
    patch_products_columns()


def _migration_0003_shops_and_shop_stock() -> None:
    patch_shops_and_shop_stock()


def _migration_0004_sales_columns() -> None:
    patch_sales_table()


MIGRATIONS: tuple[Migration, ...] = (
    Migration("0001", "create base schema", _migration_0001_initial_schema),
    Migration("0002", "add product publishing columns", _migration_0002_products_columns),
    Migration("0003", "add shops and backfill shop stock", _migration_0003_shops_and_shop_stock),
    Migration("0004", "add shop-aware sales columns", _migration_0004_sales_columns),
)


def pending_migrations() -> list[Migration]:
    applied = _applied_versions()
    return [migration for migration in MIGRATIONS if migration.version not in applied]


def migration_status() -> list[dict[str, str]]:
    applied = _applied_versions()
    return [
        {
            "version": migration.version,
            "description": migration.description,
            "status": "applied" if migration.version in applied else "pending",
        }
        for migration in MIGRATIONS
    ]


def upgrade_database(log: bool = True) -> list[str]:
    if log:
        _log_db_info()

    applied_now: list[str] = []
    for migration in pending_migrations():
        print(f"DB MIGRATION: applying {migration.version} - {migration.description}")
        try:
            migration.apply()
            _record_migration(migration)
        except Exception:
            db.session.rollback()
            print(f"DB MIGRATION ERROR: failed {migration.version}")
            raise
        applied_now.append(migration.version)
        print(f"DB MIGRATION OK: {migration.version}")

    if not applied_now:
        print("DB MIGRATION: no pending migrations")

    return applied_now
