from app import create_app
from app.extensions import db
from app.models import User

# --------- CHANGE THESE VALUES TO WHATEVER YOU WANT ----------
NEW_USERNAME = "worker1"      # login
NEW_PASSWORD = "password123"  # password
NEW_ROLE = "manager"          # "admin", "manager" or "viewer"
# -------------------------------------------------------------


def main():
    app = create_app()

    with app.app_context():
        existing = User.query.filter_by(username=NEW_USERNAME).first()
        if existing:
            print(f"User '{NEW_USERNAME}' already exists with role '{existing.role}'.")
            return

        user = User(username=NEW_USERNAME, role=NEW_ROLE)
        user.set_password(NEW_PASSWORD)
        db.session.add(user)
        db.session.commit()
        print(f"Created user: {NEW_USERNAME} (role={NEW_ROLE})")


if __name__ == "__main__":
    main()
