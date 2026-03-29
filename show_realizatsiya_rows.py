import sqlite3

con = sqlite3.connect("fabric.db")
cur = con.cursor()

rows = cur.execute("""
SELECT id, shop_id, factory_id, settlement_date, amount, currency, note, created_by_id, created_at
FROM realizatsiya_settlements
ORDER BY id DESC
""").fetchall()

for row in rows:
    print(row)

con.close()
