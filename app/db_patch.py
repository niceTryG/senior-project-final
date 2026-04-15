import os
from sqlalchemy import text, inspect
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db


def _log_db_info():
    try:
        url = str(db.engine.url)
        safe_url = (
            url.replace(db.engine.url.password or "", "***")
            if db.engine.url.password
            else url
        )
        print("DB PATCH: engine =", db.engine.dialect.name, "| url =", safe_url)
    except Exception as e:
        print("DB PATCH: could not read engine url:", e)


def _sqlite_column_exists(table_name: str, column_name: str) -> bool:
    rows = db.session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    col_names = [r[1] for r in rows]
    return column_name in col_names


def _pg_column_exists(table_name: str, column_name: str) -> bool:
    result = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return result is not None


def _generic_column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(db.engine)
    try:
        columns = inspector.get_columns(table_name)
        return any(col["name"] == column_name for col in columns)
    except Exception:
        return False


def _column_exists(table_name: str, column_name: str) -> bool:
    dialect = db.engine.dialect.name

    if dialect == "sqlite":
        return _sqlite_column_exists(table_name, column_name)

    if dialect == "postgresql":
        return _pg_column_exists(table_name, column_name)

    return _generic_column_exists(table_name, column_name)


def patch_products_columns() -> None:
    """
    Safe patch for products table:
    - SQLite: PRAGMA table_info + normal ALTER TABLE ADD COLUMN
    - Postgres: information_schema check + ALTER TABLE ADD COLUMN
    - Others: SQLAlchemy inspector check
    """
    try:
        if not _column_exists("products", "is_published"):
            db.session.execute(
                text("ALTER TABLE products ADD COLUMN is_published BOOLEAN DEFAULT 0")
            )
            print("DB PATCH: added products.is_published")

        if not _column_exists("products", "public_description"):
            db.session.execute(
                text("ALTER TABLE products ADD COLUMN public_description TEXT")
            )
            print("DB PATCH: added products.public_description")

        if not _column_exists("products", "garment_analysis_json"):
            db.session.execute(
                text("ALTER TABLE products ADD COLUMN garment_analysis_json TEXT")
            )
            print("DB PATCH: added products.garment_analysis_json")

        if not _column_exists("products", "garment_annotation_image"):
            db.session.execute(
                text("ALTER TABLE products ADD COLUMN garment_annotation_image VARCHAR(255)")
            )
            print("DB PATCH: added products.garment_annotation_image")

        if not _column_exists("products", "garment_analysis_version"):
            db.session.execute(
                text("ALTER TABLE products ADD COLUMN garment_analysis_version VARCHAR(64)")
            )
            print("DB PATCH: added products.garment_analysis_version")

        if not _column_exists("products", "garment_analysis_updated_at"):
            db.session.execute(
                text("ALTER TABLE products ADD COLUMN garment_analysis_updated_at TIMESTAMP")
            )
            print("DB PATCH: added products.garment_analysis_updated_at")

        db.session.commit()
        print("DB PATCH OK: products columns checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR:", e)
        raise


def patch_product_garment_zone_assignments_table() -> None:
    dialect = db.engine.dialect.name

    try:
        if dialect == "sqlite":
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS product_garment_zone_assignments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id INTEGER NOT NULL,
                        zone_key VARCHAR(64) NOT NULL,
                        zone_label VARCHAR(128) NOT NULL,
                        assignment_kind VARCHAR(32) NOT NULL DEFAULT 'unassigned',
                        usage_label VARCHAR(128),
                        note VARCHAR(255),
                        product_composition_id INTEGER,
                        fabric_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
                        FOREIGN KEY(product_composition_id) REFERENCES product_compositions(id) ON DELETE SET NULL,
                        FOREIGN KEY(fabric_id) REFERENCES fabrics(id) ON DELETE SET NULL,
                        CONSTRAINT uq_product_garment_zone_assignment UNIQUE (product_id, zone_key)
                    )
                    """
                )
            )
        else:
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS product_garment_zone_assignments (
                        id INTEGER PRIMARY KEY,
                        product_id INTEGER NOT NULL,
                        zone_key VARCHAR(64) NOT NULL,
                        zone_label VARCHAR(128) NOT NULL,
                        assignment_kind VARCHAR(32) NOT NULL DEFAULT 'unassigned',
                        usage_label VARCHAR(128),
                        note VARCHAR(255),
                        product_composition_id INTEGER NULL,
                        fabric_id INTEGER NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT uq_product_garment_zone_assignment UNIQUE (product_id, zone_key)
                    )
                    """
                )
            )

        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_product_garment_zone_assignments_product_id "
                "ON product_garment_zone_assignments(product_id)"
            )
        )
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_product_garment_zone_assignments_product_composition_id "
                "ON product_garment_zone_assignments(product_composition_id)"
            )
        )
        db.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_product_garment_zone_assignments_fabric_id "
                "ON product_garment_zone_assignments(fabric_id)"
            )
        )

        db.session.commit()
        print("DB PATCH OK: product garment zone assignments table checked")
        return None
    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (product garment zone assignments):", e)
        raise


def patch_shops_and_shop_stock() -> None:
    """
    Introduce shops table and shop_id columns safely.
    Also backfills existing shop_stock rows with a default shop.
    """
    dialect = db.engine.dialect.name

    try:
        # =========================
        # 1. CREATE shops table
        # =========================

        if dialect == "sqlite":
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS shops (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        factory_id INTEGER NOT NULL,
                        name VARCHAR(128) NOT NULL,
                        location VARCHAR(128),
                        note VARCHAR(255),
                        is_active BOOLEAN DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        else:  # postgres / others
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS shops (
                        id SERIAL PRIMARY KEY,
                        factory_id INTEGER NOT NULL,
                        name VARCHAR(128) NOT NULL,
                        location VARCHAR(128),
                        note VARCHAR(255),
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

        print("DB PATCH: shops table checked")

        # =========================
        # 2. users.shop_id
        # =========================

        if not _column_exists("users", "shop_id"):
            db.session.execute(text("ALTER TABLE users ADD COLUMN shop_id INTEGER"))
            print("DB PATCH: added users.shop_id")

        # =========================
        # 3. shop_stock.shop_id
        # =========================

        if not _column_exists("shop_stock", "shop_id"):
            db.session.execute(text("ALTER TABLE shop_stock ADD COLUMN shop_id INTEGER"))
            print("DB PATCH: added shop_stock.shop_id")

        db.session.commit()

        # =========================
        # 4. CREATE DEFAULT SHOPS
        # =========================

        factories = db.session.execute(text("SELECT id FROM factories")).fetchall()

        for f in factories:
            factory_id = f[0]

            shop = db.session.execute(
                text(
                    """
                    SELECT id FROM shops
                    WHERE factory_id = :factory_id
                    LIMIT 1
                    """
                ),
                {"factory_id": factory_id},
            ).first()

            if not shop:
                db.session.execute(
                    text(
                        """
                        INSERT INTO shops (factory_id, name, is_active, created_at)
                        VALUES (:factory_id, 'Main Shop', 1, CURRENT_TIMESTAMP)
                        """
                    ),
                    {"factory_id": factory_id},
                )
                print(f"DB PATCH: created default shop for factory {factory_id}")

        db.session.commit()

        # =========================
        # 5. ATTACH OLD SHOP STOCK
        # =========================

        rows = db.session.execute(
            text(
                """
                SELECT ss.id, p.factory_id
                FROM shop_stock ss
                JOIN products p ON p.id = ss.product_id
                WHERE ss.shop_id IS NULL
                """
            )
        ).fetchall()

        for row in rows:
            stock_id = row[0]
            factory_id = row[1]

            shop = db.session.execute(
                text(
                    """
                    SELECT id FROM shops
                    WHERE factory_id = :factory_id
                    LIMIT 1
                    """
                ),
                {"factory_id": factory_id},
            ).first()

            if shop:
                db.session.execute(
                    text(
                        """
                        UPDATE shop_stock
                        SET shop_id = :shop_id
                        WHERE id = :stock_id
                        """
                    ),
                    {"shop_id": shop[0], "stock_id": stock_id},
                )

        db.session.commit()

        print("DB PATCH OK: shops + shop_stock updated")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (shops):", e)
        raise


def patch_sales_table() -> None:
    """
    Add missing sales columns for shop-aware regular sales.
    Safe + idempotent for SQLite and Postgres.
    """
    dialect = db.engine.dialect.name

    try:
        if not _column_exists("sales", "shop_id"):
            db.session.execute(text("ALTER TABLE sales ADD COLUMN shop_id INTEGER"))
            print("DB PATCH: added sales.shop_id")

        if not _column_exists("sales", "created_by_id"):
            db.session.execute(text("ALTER TABLE sales ADD COLUMN created_by_id INTEGER"))
            print("DB PATCH: added sales.created_by_id")

        if not _column_exists("sales", "created_at"):
            if dialect == "sqlite":
                db.session.execute(text("ALTER TABLE sales ADD COLUMN created_at DATETIME"))
            else:
                db.session.execute(text("ALTER TABLE sales ADD COLUMN created_at TIMESTAMP"))
            print("DB PATCH: added sales.created_at")

        db.session.execute(
            text(
                """
                UPDATE sales
                SET created_at = CURRENT_TIMESTAMP
                WHERE created_at IS NULL
                """
            )
        )

        db.session.commit()
        print("DB PATCH OK: sales columns checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (sales):", e)
        raise


def patch_production_plans_table() -> None:
    dialect = db.engine.dialect.name

    try:
        if dialect == "sqlite":
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS production_plans (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        factory_id INTEGER NOT NULL,
                        product_id INTEGER NOT NULL,
                        order_item_id INTEGER,
                        created_by_id INTEGER,
                        target_qty INTEGER NOT NULL DEFAULT 1,
                        max_producible_units INTEGER NOT NULL DEFAULT 0,
                        shortage_count INTEGER NOT NULL DEFAULT 0,
                        can_fulfill_plan BOOLEAN NOT NULL DEFAULT 0,
                        note VARCHAR(255),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.session.execute(
                text("CREATE INDEX IF NOT EXISTS ix_production_plans_factory_id ON production_plans(factory_id)")
            )
            db.session.execute(
                text("CREATE INDEX IF NOT EXISTS ix_production_plans_product_id ON production_plans(product_id)")
            )
            db.session.execute(
                text("CREATE INDEX IF NOT EXISTS ix_production_plans_order_item_id ON production_plans(order_item_id)")
            )
            db.session.execute(
                text("CREATE INDEX IF NOT EXISTS ix_production_plans_created_at ON production_plans(created_at)")
            )
        else:
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS production_plans (
                        id SERIAL PRIMARY KEY,
                        factory_id INTEGER NOT NULL,
                        product_id INTEGER NOT NULL,
                        order_item_id INTEGER NULL,
                        created_by_id INTEGER NULL,
                        target_qty INTEGER NOT NULL DEFAULT 1,
                        max_producible_units INTEGER NOT NULL DEFAULT 0,
                        shortage_count INTEGER NOT NULL DEFAULT 0,
                        can_fulfill_plan BOOLEAN NOT NULL DEFAULT FALSE,
                        note VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

        db.session.commit()
        print("DB PATCH OK: production_plans table checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (production_plans):", e)
        raise


def patch_fabrics_supplier_column() -> None:
    try:
        if not _column_exists("fabrics", "supplier_name"):
            db.session.execute(text("ALTER TABLE fabrics ADD COLUMN supplier_name VARCHAR(128)"))
            print("DB PATCH: added fabrics.supplier_name")

        db.session.commit()
        print("DB PATCH OK: fabrics supplier column checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (fabrics supplier):", e)
        raise


def patch_supplier_receipts_table() -> None:
    dialect = db.engine.dialect.name

    try:
        if dialect == "sqlite":
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS supplier_receipts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        factory_id INTEGER NOT NULL,
                        fabric_id INTEGER,
                        created_by_id INTEGER,
                        supplier_name VARCHAR(128) NOT NULL,
                        material_name VARCHAR(128) NOT NULL,
                        quantity_received FLOAT NOT NULL DEFAULT 0,
                        unit VARCHAR(16) NOT NULL DEFAULT 'pcs',
                        unit_cost FLOAT,
                        currency VARCHAR(3) DEFAULT 'UZS',
                        note VARCHAR(255),
                        received_at DATE NOT NULL DEFAULT CURRENT_DATE,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                    )
                    """
                )
            )
        else:
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS supplier_receipts (
                        id SERIAL PRIMARY KEY,
                        factory_id INTEGER NOT NULL,
                        fabric_id INTEGER,
                        created_by_id INTEGER,
                        supplier_name VARCHAR(128) NOT NULL,
                        material_name VARCHAR(128) NOT NULL,
                        quantity_received FLOAT NOT NULL DEFAULT 0,
                        unit VARCHAR(16) NOT NULL DEFAULT 'pcs',
                        unit_cost FLOAT,
                        currency VARCHAR(3) DEFAULT 'UZS',
                        note VARCHAR(255),
                        received_at DATE NOT NULL DEFAULT CURRENT_DATE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                    )
                    """
                )
            )

        db.session.commit()
        print("DB PATCH OK: supplier_receipts table checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (supplier receipts):", e)
        raise


def patch_supplier_receipts_payment_columns() -> None:
    try:
        if not _column_exists("supplier_receipts", "invoice_number"):
            db.session.execute(text("ALTER TABLE supplier_receipts ADD COLUMN invoice_number VARCHAR(64)"))
            print("DB PATCH: added supplier_receipts.invoice_number")

        if not _column_exists("supplier_receipts", "payment_status"):
            db.session.execute(text("ALTER TABLE supplier_receipts ADD COLUMN payment_status VARCHAR(16) DEFAULT 'unpaid'"))
            print("DB PATCH: added supplier_receipts.payment_status")

        db.session.execute(
            text(
                """
                UPDATE supplier_receipts
                SET payment_status = COALESCE(NULLIF(payment_status, ''), 'unpaid')
                """
            )
        )

        db.session.commit()
        print("DB PATCH OK: supplier_receipts payment columns checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (supplier receipts payment columns):", e)
        raise


def patch_supplier_profiles_table() -> None:
    dialect = db.engine.dialect.name

    try:
        if dialect == "sqlite":
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS supplier_profiles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        factory_id INTEGER NOT NULL,
                        supplier_name VARCHAR(128) NOT NULL,
                        contact_person VARCHAR(128),
                        phone VARCHAR(64),
                        telegram_handle VARCHAR(64),
                        note VARCHAR(255),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        CONSTRAINT uq_supplier_profiles_factory_supplier UNIQUE (factory_id, supplier_name)
                    )
                    """
                )
            )
        else:
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS supplier_profiles (
                        id SERIAL PRIMARY KEY,
                        factory_id INTEGER NOT NULL,
                        supplier_name VARCHAR(128) NOT NULL,
                        contact_person VARCHAR(128),
                        phone VARCHAR(64),
                        telegram_handle VARCHAR(64),
                        note VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        CONSTRAINT uq_supplier_profiles_factory_supplier UNIQUE (factory_id, supplier_name)
                    )
                    """
                )
            )

        db.session.commit()
        print("DB PATCH OK: supplier_profiles table checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (supplier profiles):", e)
        raise


def patch_cuts_detail_columns() -> None:
    try:
        if not _column_exists("cuts", "remaining_quantity"):
            db.session.execute(text("ALTER TABLE cuts ADD COLUMN remaining_quantity FLOAT"))
            print("DB PATCH: added cuts.remaining_quantity")

        if not _column_exists("cuts", "comment"):
            db.session.execute(text("ALTER TABLE cuts ADD COLUMN comment VARCHAR(255)"))
            print("DB PATCH: added cuts.comment")

        if not _column_exists("cuts", "created_by_id"):
            db.session.execute(text("ALTER TABLE cuts ADD COLUMN created_by_id INTEGER"))
            print("DB PATCH: added cuts.created_by_id")

        db.session.commit()
        print("DB PATCH OK: cuts detail columns checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (cuts detail columns):", e)
        raise


def patch_productions_plan_column() -> None:
    try:
        if not _column_exists("productions", "production_plan_id"):
            db.session.execute(text("ALTER TABLE productions ADD COLUMN production_plan_id INTEGER"))
            print("DB PATCH: added productions.production_plan_id")

        db.session.commit()
        print("DB PATCH OK: productions plan column checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (productions plan column):", e)
        raise


def patch_users_identity_columns() -> None:
    try:
        if not _column_exists("users", "full_name"):
            db.session.execute(text("ALTER TABLE users ADD COLUMN full_name VARCHAR(128)"))
            print("DB PATCH: added users.full_name")

        if not _column_exists("users", "phone"):
            db.session.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(64)"))
            print("DB PATCH: added users.phone")

        db.session.commit()
        print("DB PATCH OK: users identity columns checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (users identity):", e)
        raise


def patch_factory_owner_column() -> None:
    try:
        if not _column_exists("factories", "owner_user_id"):
            db.session.execute(text("ALTER TABLE factories ADD COLUMN owner_user_id INTEGER"))
            print("DB PATCH: added factories.owner_user_id")

        db.session.commit()

        factory_rows = db.session.execute(
            text(
                """
                SELECT id
                FROM factories
                WHERE owner_user_id IS NULL
                """
            )
        ).fetchall()

        for (factory_id,) in factory_rows:
            owner_row = db.session.execute(
                text(
                    """
                    SELECT id
                    FROM users
                    WHERE factory_id = :factory_id
                      AND role = 'admin'
                    ORDER BY id ASC
                    LIMIT 1
                    """
                ),
                {"factory_id": factory_id},
            ).first()

            if not owner_row:
                owner_row = db.session.execute(
                    text(
                        """
                        SELECT id
                        FROM users
                        WHERE factory_id = :factory_id
                        ORDER BY id ASC
                        LIMIT 1
                        """
                    ),
                    {"factory_id": factory_id},
                ).first()

            if owner_row:
                db.session.execute(
                    text(
                        """
                        UPDATE factories
                        SET owner_user_id = :owner_user_id
                        WHERE id = :factory_id
                          AND owner_user_id IS NULL
                        """
                    ),
                    {
                        "factory_id": factory_id,
                        "owner_user_id": owner_row[0],
                    },
                )

        db.session.commit()
        print("DB PATCH OK: factory owner column checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (factory owner):", e)
        raise


def patch_operational_tasks_table() -> None:
    dialect = db.engine.dialect.name

    try:
        if dialect == "sqlite":
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS operational_tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        factory_id INTEGER NOT NULL,
                        shop_id INTEGER,
                        assigned_user_id INTEGER,
                        created_by_id INTEGER,
                        closed_by_id INTEGER,
                        task_type VARCHAR(64) NOT NULL DEFAULT 'manual',
                        source_type VARCHAR(64),
                        source_id INTEGER,
                        title VARCHAR(160) NOT NULL,
                        description VARCHAR(255),
                        action_url VARCHAR(255),
                        target_role VARCHAR(32),
                        priority VARCHAR(16) NOT NULL DEFAULT 'medium',
                        status VARCHAR(16) NOT NULL DEFAULT 'open',
                        due_date DATE,
                        is_system_generated BOOLEAN NOT NULL DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        closed_at DATETIME
                    )
                    """
                )
            )
        else:
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS operational_tasks (
                        id SERIAL PRIMARY KEY,
                        factory_id INTEGER NOT NULL,
                        shop_id INTEGER,
                        assigned_user_id INTEGER,
                        created_by_id INTEGER,
                        closed_by_id INTEGER,
                        task_type VARCHAR(64) NOT NULL DEFAULT 'manual',
                        source_type VARCHAR(64),
                        source_id INTEGER,
                        title VARCHAR(160) NOT NULL,
                        description VARCHAR(255),
                        action_url VARCHAR(255),
                        target_role VARCHAR(32),
                        priority VARCHAR(16) NOT NULL DEFAULT 'medium',
                        status VARCHAR(16) NOT NULL DEFAULT 'open',
                        due_date DATE,
                        is_system_generated BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        closed_at TIMESTAMP
                    )
                    """
                )
            )

        db.session.commit()
        print("DB PATCH OK: operational_tasks table checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (operational tasks):", e)
        raise


def patch_onboarding_telegram_verifications_table() -> None:
    dialect = db.engine.dialect.name

    try:
        if dialect == "sqlite":
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS onboarding_telegram_verifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token VARCHAR(64) NOT NULL UNIQUE,
                        phone VARCHAR(64) NOT NULL,
                        full_name VARCHAR(128),
                        telegram_chat_id BIGINT,
                        expires_at DATETIME NOT NULL,
                        verified_at DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                    )
                    """
                )
            )
        else:
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS onboarding_telegram_verifications (
                        id SERIAL PRIMARY KEY,
                        token VARCHAR(64) NOT NULL UNIQUE,
                        phone VARCHAR(64) NOT NULL,
                        full_name VARCHAR(128),
                        telegram_chat_id BIGINT,
                        expires_at TIMESTAMP NOT NULL,
                        verified_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                    )
                    """
                )
            )

        db.session.commit()
        print("DB PATCH OK: onboarding telegram verifications table checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (onboarding telegram verifications):", e)
        raise


def patch_user_login_security_columns() -> None:
    try:
        if not _column_exists("users", "must_change_password"):
            db.session.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 0"))
            print("DB PATCH: added users.must_change_password")

        if not _column_exists("users", "failed_login_attempts"):
            db.session.execute(text("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0"))
            print("DB PATCH: added users.failed_login_attempts")

        if not _column_exists("users", "locked_until"):
            db.session.execute(text("ALTER TABLE users ADD COLUMN locked_until DATETIME"))
            print("DB PATCH: added users.locked_until")

        if not _column_exists("users", "last_login_at"):
            db.session.execute(text("ALTER TABLE users ADD COLUMN last_login_at DATETIME"))
            print("DB PATCH: added users.last_login_at")

        if not _column_exists("users", "password_changed_at"):
            db.session.execute(text("ALTER TABLE users ADD COLUMN password_changed_at DATETIME"))
            print("DB PATCH: added users.password_changed_at")

        db.session.execute(
            text(
                """
                UPDATE users
                SET must_change_password = COALESCE(must_change_password, 0),
                    failed_login_attempts = COALESCE(failed_login_attempts, 0)
                """
            )
        )

        db.session.commit()
        print("DB PATCH OK: user login security columns checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (user login security):", e)
        raise


def patch_fabrics_material_columns() -> None:
    try:
        if not _column_exists("fabrics", "material_type"):
            db.session.execute(
                text("ALTER TABLE fabrics ADD COLUMN material_type VARCHAR(32) DEFAULT 'fabric'")
            )
            print("DB PATCH: added fabrics.material_type")

        if not _column_exists("fabrics", "min_stock_quantity"):
            db.session.execute(
                text("ALTER TABLE fabrics ADD COLUMN min_stock_quantity FLOAT DEFAULT 5")
            )
            print("DB PATCH: added fabrics.min_stock_quantity")

        db.session.execute(
            text(
                """
                UPDATE fabrics
                SET material_type = COALESCE(NULLIF(material_type, ''), 'fabric'),
                    min_stock_quantity = COALESCE(min_stock_quantity, 5)
                """
            )
        )

        db.session.commit()
        print("DB PATCH OK: fabrics material columns checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR (fabrics material columns):", e)
        raise

def apply_db_patches() -> None:
    """
    Main entry.
    Safe + idempotent for local SQLite and Render Postgres.
    """
    _log_db_info()

    try:
        patch_products_columns()
        patch_shops_and_shop_stock()
        patch_sales_table()
        patch_users_identity_columns()
        patch_factory_owner_column()
        patch_operational_tasks_table()
        patch_onboarding_telegram_verifications_table()
        patch_user_login_security_columns()
        patch_fabrics_material_columns()

    except SQLAlchemyError as e:
        db.session.rollback()
        print("DB PATCH ERROR:", e)
        raise
    except Exception as e:
        db.session.rollback()
        print("DB PATCH UNEXPECTED ERROR:", e)
        raise
