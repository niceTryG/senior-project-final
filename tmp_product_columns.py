from app import create_app
from app.models import Product

app = create_app()

with app.app_context():
    print("PRODUCT TABLE COLUMNS:")
    for c in Product.__table__.columns:
        print(f"{c.name} | nullable={c.nullable} | default={c.default}")
