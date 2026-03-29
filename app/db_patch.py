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

        db.session.commit()
        print("DB PATCH OK: products columns checked")
        return None

    except Exception as e:
        db.session.rollback()
        print("DB PATCH ERROR:", e)
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

    except SQLAlchemyError as e:
        db.session.rollback()
        print("DB PATCH ERROR:", e)
        raise
    except Exception as e:
        db.session.rollback()
        print("DB PATCH UNEXPECTED ERROR:", e)
        raise
