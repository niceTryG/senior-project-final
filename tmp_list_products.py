from app import create_app
from app.models import Product

REAL_FACTORY_ID = 1   # change this after checking factories

app = create_app()

with app.app_context():
    rows = Product.query.filter(Product.factory_id == REAL_FACTORY_ID).order_by(Product.name).all()
    for p in rows:
        print(f"{p.id} | {p.name}")
