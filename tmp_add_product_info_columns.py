from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    db.session.execute(text("ALTER TABLE products ADD COLUMN website_image VARCHAR(255)"))
    db.session.execute(text("ALTER TABLE products ADD COLUMN fabric_used VARCHAR(255)"))
    db.session.execute(text("ALTER TABLE products ADD COLUMN notes TEXT"))
    db.session.commit()
    print("DONE: added website_image, fabric_used, notes")
