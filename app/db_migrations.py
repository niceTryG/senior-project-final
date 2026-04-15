from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text

from .db_patch import (
    _log_db_info,
    patch_factory_owner_column,
    patch_onboarding_telegram_verifications_table,
    patch_operational_tasks_table,
    patch_product_garment_zone_assignments_table,
    patch_fabrics_material_columns,
    patch_fabrics_supplier_column,
    patch_productions_plan_column,
    patch_production_plans_table,
    patch_cuts_detail_columns,
    patch_supplier_profiles_table,
    patch_supplier_receipts_payment_columns,
    patch_supplier_receipts_table,
    patch_products_columns,
    patch_sales_table,
    patch_shops_and_shop_stock,
    patch_user_login_security_columns,
    patch_users_identity_columns,
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


def _migration_0005_users_identity_columns() -> None:
    patch_users_identity_columns()


def _migration_0006_factory_owner_column() -> None:
    patch_factory_owner_column()


def _migration_0007_operational_tasks_table() -> None:
    patch_operational_tasks_table()


def _migration_0008_onboarding_telegram_verifications_table() -> None:
    patch_onboarding_telegram_verifications_table()


def _migration_0009_user_login_security_columns() -> None:
    patch_user_login_security_columns()


def _migration_0010_fabrics_material_columns() -> None:
    patch_fabrics_material_columns()


def _migration_0011_production_plans_table() -> None:
    patch_production_plans_table()


def _migration_0012_fabrics_supplier_column() -> None:
    patch_fabrics_supplier_column()


def _migration_0013_supplier_receipts_table() -> None:
    patch_supplier_receipts_table()


def _migration_0014_supplier_receipts_payment_columns() -> None:
    patch_supplier_receipts_payment_columns()


def _migration_0015_supplier_profiles_table() -> None:
    patch_supplier_profiles_table()


def _migration_0016_productions_plan_column() -> None:
    patch_productions_plan_column()


def _migration_0017_cuts_detail_columns() -> None:
    patch_cuts_detail_columns()


def _migration_0018_product_garment_analysis_columns() -> None:
    patch_products_columns()


def _migration_0019_product_garment_zone_assignments_table() -> None:
    patch_product_garment_zone_assignments_table()


MIGRATIONS: tuple[Migration, ...] = (
    Migration("0001", "create base schema", _migration_0001_initial_schema),
    Migration("0002", "add product publishing columns", _migration_0002_products_columns),
    Migration("0003", "add shops and backfill shop stock", _migration_0003_shops_and_shop_stock),
    Migration("0004", "add shop-aware sales columns", _migration_0004_sales_columns),
    Migration("0005", "add user full name and phone columns", _migration_0005_users_identity_columns),
    Migration("0006", "add explicit workspace owner column", _migration_0006_factory_owner_column),
    Migration("0007", "add operational tasks table", _migration_0007_operational_tasks_table),
    Migration("0008", "add onboarding telegram verification table", _migration_0008_onboarding_telegram_verifications_table),
    Migration("0009", "add user login security columns", _migration_0009_user_login_security_columns),
    Migration("0010", "add materials columns to fabrics table", _migration_0010_fabrics_material_columns),
    Migration("0011", "add production plans table", _migration_0011_production_plans_table),
    Migration("0012", "add supplier field to fabrics table", _migration_0012_fabrics_supplier_column),
    Migration("0013", "add supplier receipts table", _migration_0013_supplier_receipts_table),
    Migration("0014", "add supplier receipt payment columns", _migration_0014_supplier_receipts_payment_columns),
    Migration("0015", "add supplier profiles table", _migration_0015_supplier_profiles_table),
    Migration("0016", "link productions to saved plans", _migration_0016_productions_plan_column),
    Migration("0017", "add cut detail columns", _migration_0017_cuts_detail_columns),
    Migration("0018", "add product garment analysis columns", _migration_0018_product_garment_analysis_columns),
    Migration("0019", "add product garment zone assignments table", _migration_0019_product_garment_zone_assignments_table),
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
