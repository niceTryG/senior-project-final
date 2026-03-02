# app/db_patch.py
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db


def apply_db_patches() -> None:
    """
    Safe, idempotent DB patching.
    Runs inside Render (so internal DATABASE_URL works).
    """
    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    ALTER TABLE products
                    ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT FALSE;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE products
                    ADD COLUMN IF NOT EXISTS public_description TEXT;
                    """
                )
            )
    except SQLAlchemyError as e:
        # Don't crash the whole app if patch fails.
        # You can log it instead.
        print("DB PATCH ERROR:", e)