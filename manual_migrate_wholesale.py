from sqlalchemy import text

from app import create_app
from app.extensions import db

app = create_app()

def table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).fetchone()
    return row is not None

with app.app_context():
    conn = db.engine.connect()
    trans = conn.begin()

    try:
        db.create_all()

        if table_exists(conn, "wholesale_sales"):
            cols = conn.execute(text("PRAGMA table_info(wholesale_sales)")).fetchall()
            col_map = {c[1]: c for c in cols}

            factory_col = col_map.get("factory_id")
            if factory_col and factory_col[3] == 1:
                conn.execute(text("""
                    CREATE TABLE wholesale_sales_new (
                        id INTEGER PRIMARY KEY,
                        factory_id INTEGER NULL,
                        shop_id INTEGER NOT NULL,
                        created_by_id INTEGER,
                        created_at DATETIME NOT NULL,
                        sale_date DATE NOT NULL,
                        customer_name VARCHAR(128),
                        customer_phone VARCHAR(64),
                        note VARCHAR(255),
                        total_skus INTEGER NOT NULL DEFAULT 0,
                        total_qty INTEGER NOT NULL DEFAULT 0,
                        subtotal_amount FLOAT NOT NULL DEFAULT 0.0,
                        discount_amount FLOAT NOT NULL DEFAULT 0.0,
                        total_amount FLOAT NOT NULL DEFAULT 0.0,
                        currency VARCHAR(3) NOT NULL DEFAULT 'UZS',
                        payment_status VARCHAR(32) NOT NULL DEFAULT 'paid',
                        payment_method VARCHAR(32),
                        FOREIGN KEY(factory_id) REFERENCES factories (id),
                        FOREIGN KEY(shop_id) REFERENCES shops (id),
                        FOREIGN KEY(created_by_id) REFERENCES users (id)
                    )
                """))

                conn.execute(text("""
                    INSERT INTO wholesale_sales_new (
                        id, factory_id, shop_id, created_by_id, created_at, sale_date,
                        customer_name, customer_phone, note,
                        total_skus, total_qty, subtotal_amount, discount_amount,
                        total_amount, currency, payment_status, payment_method
                    )
                    SELECT
                        id, factory_id, shop_id, created_by_id, created_at, sale_date,
                        customer_name, customer_phone, note,
                        total_skus, total_qty, subtotal_amount, discount_amount,
                        total_amount, currency, payment_status, payment_method
                    FROM wholesale_sales
                """))

                conn.execute(text("DROP TABLE wholesale_sales"))
                conn.execute(text("ALTER TABLE wholesale_sales_new RENAME TO wholesale_sales"))

                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_wholesale_sales_factory_id ON wholesale_sales(factory_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_wholesale_sales_shop_id ON wholesale_sales(shop_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_wholesale_sales_created_by_id ON wholesale_sales(created_by_id)"
                ))

        trans.commit()
        print("Wholesale migration completed successfully.")

    except Exception as e:
        trans.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        conn.close()
