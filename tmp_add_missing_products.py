from app import create_app, db
from app.models import Product

FACTORY_ID = 1

missing_products = [
    "lion",
    "polosa",
    "polosa lion",
    "sundus gijim",
    "ninachi",
    "namangan obodog",
    "namangan ramashka",
    "ramashka obodog",
    "obodog",
    "kate",
    "katak",
    "star",
]

app = create_app()

with app.app_context():
    for name in missing_products:
        exists = (
            Product.query
            .filter(Product.factory_id == FACTORY_ID)
            .filter(Product.name.ilike(name))
            .first()
        )
        if exists:
            print(f"SKIP EXISTS: {exists.name}")
            continue

        p = Product(
            factory_id=FACTORY_ID,
            name=name
        )
        db.session.add(p)
        print(f"ADDED PRODUCT: {name}")

    db.session.commit()
    print("DONE")
