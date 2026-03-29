from app import create_app
from app.models import User, Factory, Shop

app = create_app()

with app.app_context():
    rows = User.query.order_by(User.id.asc()).all()
    for u in rows:
        factory_name = u.factory.name if u.factory else None
        shop_name = u.shop.name if u.shop else None
        print(f"{u.id} | {u.username} | role={u.role} | factory_id={u.factory_id} | factory={factory_name} | shop_id={u.shop_id} | shop={shop_name}")
