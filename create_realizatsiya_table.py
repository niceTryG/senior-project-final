import sqlite3
from datetime import datetime

db = r"fabric.db"
con = sqlite3.connect(db)
cur = con.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS realizatsiya_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL,
    factory_id INTEGER NOT NULL,
    settlement_date DATE NOT NULL,
    amount FLOAT NOT NULL DEFAULT 0.0,
    currency VARCHAR(3) NOT NULL DEFAULT 'UZS',
    note VARCHAR(255),
    created_by_id INTEGER,
    created_at DATETIME NOT NULL,
    CONSTRAINT ck_realizatsiya_settlements_amount_positive CHECK (amount > 0),
    FOREIGN KEY(shop_id) REFERENCES shops(id),
    FOREIGN KEY(factory_id) REFERENCES factories(id),
    FOREIGN KEY(created_by_id) REFERENCES users(id)
)
""")

cur.execute("CREATE INDEX IF NOT EXISTS ix_realizatsiya_settlements_shop_id ON realizatsiya_settlements (shop_id)")
cur.execute("CREATE INDEX IF NOT EXISTS ix_realizatsiya_settlements_factory_id ON realizatsiya_settlements (factory_id)")
cur.execute("CREATE INDEX IF NOT EXISTS ix_realizatsiya_settlements_created_by_id ON realizatsiya_settlements (created_by_id)")

con.commit()
con.close()

print("OK: realizatsiya_settlements created")
