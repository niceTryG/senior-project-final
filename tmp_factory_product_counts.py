from app import create_app
from app.models import Factory, Product
from sqlalchemy import func

app = create_app()

with app.app_context():
    rows = (
        Product.query
        .with_entities(Product.factory_id, func.count(Product.id))
        .group_by(Product.factory_id)
        .all()
    )

    print("PRODUCT COUNTS BY FACTORY:")
    for factory_id, cnt in rows:
        factory = Factory.query.get(factory_id)
        factory_name = getattr(factory, "name", None) if factory else None
        print(f"{factory_id} | {factory_name} | {cnt}")
