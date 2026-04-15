from app import create_app, db
from app.models import User

USERNAME = "iiibrohim"
PASSWORD = "Musakh17"

app = create_app()

with app.app_context():
    existing = User.query.filter_by(username=USERNAME).first()

    if existing:
        existing.role = "superadmin"
        existing.factory_id = None
        existing.shop_id = None
        existing.set_password(PASSWORD)
        db.session.commit()
        print(f"UPDATED SUPERADMIN: {existing.username}")
    else:
        user = User(
            username=USERNAME,
            role="superadmin",
            factory_id=None,
            shop_id=None,
        )
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        print(f"CREATED SUPERADMIN: {user.username}")
