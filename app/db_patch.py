# app/db_patch.py

import os
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db
from .models import User


def apply_db_patches() -> None:
    """
    Safe, idempotent DB patching.
    Runs inside Render (so internal DATABASE_URL works).
    """

    try:
        # ----------------------------------------
        # 1️⃣ Ensure required Product columns exist
        # ----------------------------------------
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

        # ----------------------------------------
        # 2️⃣ Bootstrap first admin (env-based)
        # ----------------------------------------
        username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "").strip()
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()

        if username and password:
            # Only create if NO users exist
            if db.session.query(User.id).first() is None:
                admin = User(username=username, role="admin")
                admin.set_password(password)

                db.session.add(admin)
                db.session.commit()

                print("✅ Bootstrap admin created from env variables.")

    except SQLAlchemyError as e:
        # Do NOT crash the whole app if patch fails
        db.session.rollback()
        print("DB PATCH ERROR:", e)