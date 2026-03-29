import sqlite3

DB_PATH = "fabric.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("Old shop_stock schema:")
for row in cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='shop_stock'"):
    print(row[0])

cur.execute("ALTER TABLE shop_stock RENAME TO shop_stock_old")

cur.execute("""
CREATE TABLE shop_stock (
    id INTEGER PRIMARY KEY,
    shop_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    source_factory_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(shop_id) REFERENCES shops(id),
    FOREIGN KEY(product_id) REFERENCES products(id),
    FOREIGN KEY(source_factory_id) REFERENCES factories(id),
    CONSTRAINT uq_shop_stock_shop_product_factory
        UNIQUE (shop_id, product_id, source_factory_id)
)
""")

cur.execute("""
INSERT INTO shop_stock (id, shop_id, product_id, source_factory_id, quantity)
SELECT
    ss.id,
    COALESCE(ss.shop_id, 1) AS shop_id,
    ss.product_id,
    p.factory_id AS source_factory_id,
    ss.quantity
FROM shop_stock_old ss
JOIN products p ON p.id = ss.product_id
""")

cur.execute("DROP TABLE shop_stock_old")

conn.commit()

print("\nNew shop_stock schema:")
for row in cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='shop_stock'"):
    print(row[0])

print("\nRows after migration:")
for row in cur.execute("SELECT id, shop_id, product_id, source_factory_id, quantity FROM shop_stock ORDER BY id LIMIT 20"):
    print(row)

conn.close()
print("\nDone.")
