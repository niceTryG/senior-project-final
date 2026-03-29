import sqlite3

DB_PATH = "fabric.db"
DEFAULT_SHOP_ID = 1  # fallback for old sales/shop movements without explicit shop id

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("Rebuilding shop_stock from history...")

# Start fresh
cur.execute("DELETE FROM shop_stock")

# -------------------------
# 1) Rebuild incoming stock from movements
# -------------------------
movement_rows = cur.execute("""
    SELECT id, factory_id, product_id, source, destination, change, note
    FROM movements
    ORDER BY id ASC
""").fetchall()

rebuilt = {}

for row in movement_rows:
    movement_id, factory_id, product_id, source, destination, change, note = row

    if not product_id or not change:
        continue

    shop_id = None
    source_factory_id = None
    qty = int(change or 0)

    source = source or ""
    destination = destination or ""

    # Case 1: factory:2 -> shop:2
    if source.startswith("factory:") and destination.startswith("shop:"):
        try:
            source_factory_id = int(source.split(":")[1])
            shop_id = int(destination.split(":")[1])
        except Exception:
            continue

    # Case 2: older style factory -> shop (shop id missing)
    elif source == "factory" and destination == "shop":
        source_factory_id = factory_id
        shop_id = DEFAULT_SHOP_ID

    else:
        continue

    if qty <= 0:
        continue

    key = (shop_id, product_id, source_factory_id)
    rebuilt[key] = rebuilt.get(key, 0) + qty

# -------------------------
# 2) Subtract sales
# -------------------------
sales_rows = cur.execute("""
    SELECT s.id, s.product_id, s.quantity, p.factory_id
    FROM sales s
    JOIN products p ON p.id = s.product_id
    ORDER BY s.id ASC
""").fetchall()

for sale_id, product_id, quantity, source_factory_id in sales_rows:
    qty = int(quantity or 0)
    if qty <= 0:
        continue

    key = (DEFAULT_SHOP_ID, product_id, source_factory_id)
    rebuilt[key] = rebuilt.get(key, 0) - qty

# -------------------------
# 3) Insert nonzero positive rows
# -------------------------
inserted = 0
skipped_negative = []

for (shop_id, product_id, source_factory_id), quantity in sorted(rebuilt.items()):
    if quantity <= 0:
        skipped_negative.append((shop_id, product_id, source_factory_id, quantity))
        continue

    cur.execute("""
        INSERT INTO shop_stock (shop_id, product_id, source_factory_id, quantity)
        VALUES (?, ?, ?, ?)
    """, (shop_id, product_id, source_factory_id, quantity))
    inserted += 1

conn.commit()

print(f"Inserted rows: {inserted}")

print("\nCurrent shop_stock rows:")
for row in cur.execute("""
    SELECT id, shop_id, product_id, source_factory_id, quantity
    FROM shop_stock
    ORDER BY shop_id, source_factory_id, product_id
"""):
    print(row)

if skipped_negative:
    print("\nSkipped rows with <= 0 quantity:")
    for row in skipped_negative[:20]:
        print(row)

conn.close()
print("\nDone.")