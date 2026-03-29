from app import create_app
from app.models import Factory

app = create_app()

with app.app_context():
    rows = Factory.query.order_by(Factory.id).all()
    for f in rows:
        print(f"{f.id} | {getattr(f, 'name', None)}")
