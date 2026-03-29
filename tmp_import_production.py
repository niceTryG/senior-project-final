import csv
from datetime import date
from app import create_app, db
from app.models import Product, Production

FACTORY_ID = 1
CSV_PATH = "production_batch_today.csv"

app = create_app()

with app.app_context():
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            raw_name = (row.get("name") or "").strip()
            raw_qty = int((row.get("qty") or "0").strip())

            product = (
                Product.query
                .filter(Product.factory_id == FACTORY_ID)
                .filter(Product.name.ilike(raw_name))
                .first()
            )

            if not product:
                print(f"NOT FOUND: {raw_name}")
                continue

            prod = Production(
                factory_id=FACTORY_ID,
                product_id=product.id,
                quantity=raw_qty,
                produced_on=date.today()
            )
            db.session.add(prod)
            print(f"ADDED: {product.name} -> {raw_qty}")

        db.session.commit()
        print("DONE")
