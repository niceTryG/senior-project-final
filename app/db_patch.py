# app/db_patch.py

import os
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db


def _log_db_info():
    try:
        url = str(db.engine.url)
        # hide password in logs
        safe_url = url.replace(db.engine.url.password or "", "***") if db.engine.url.password else url
        print("DB PATCH: engine =", db.engine.dialect.name, "| url =", safe_url)
    except Exception as e:
        print("DB PATCH: could not read engine url:", e)


def _pg_column_exists(table: str, column: str) -> bool:
    row = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table AND column_name = :col
            LIMIT 1
            """
        ),
        {"table": table, "col": column},
    ).first()
    return row is not None


def apply_db_patches() -> None:
    """
    Safe, idempotent DB patching.
    Designed for Render Postgres, but logs what DB it actually hits.
    """
    _log_db_info()

    try:
        dialect = db.engine.dialect.name

        # Ensure tables exist (in case this runs early)
        # NOTE: create_all is done in create_app, but this keeps us safe.
        # We avoid importing models here to prevent circular imports.

        if dialect == "postgresql":
            # Add is_published
            if not _pg_column_exists("products", "is_published"):
                db.session.execute(
                    text("ALTER TABLE products ADD COLUMN is_published BOOLEAN NOT NULL DEFAULT FALSE")
                )
                db.session.commit()
                print("DB PATCH: added products.is_published")

            # Add public_description
            if not _pg_column_exists("products", "public_description"):
                db.session.execute(
                    text("ALTER TABLE products ADD COLUMN public_description TEXT")
                )
                db.session.commit()
                print("DB PATCH: added products.public_description")

        else:
            # Best-effort generic (may work on sqlite too)
            db.session.execute(
                text("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_published BOOLEAN")
            )
            db.session.execute(
                text("ALTER TABLE products ADD COLUMN IF NOT EXISTS public_description TEXT")
            )
            db.session.commit()
            print("DB PATCH: generic alter attempted")

    except SQLAlchemyError as e:
        db.session.rollback()
        print("DB PATCH ERROR:", e)
    except Exception as e:
        db.session.rollback()
        print("DB PATCH UNEXPECTED ERROR:", e)