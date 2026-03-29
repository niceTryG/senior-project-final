import csv
from difflib import get_close_matches
from app import create_app
from app.models import Product

FACTORY_ID = 1
CSV_PATH = "production_batch_today.csv"

app = create_app()

with app.app_context():
    products = Product.query.filter(Product.factory_id == FACTORY_ID).all()
    product_names = [p.name for p in products]

    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            raw_name = (row.get("name") or "").strip()
            matches = get_close_matches(raw_name, product_names, n=5, cutoff=0.2)
            print(f"\nCSV: {raw_name}")
            if matches:
                for m in matches:
                    print(f"  -> {m}")
            else:
                print("  -> NO CLOSE MATCHES")
