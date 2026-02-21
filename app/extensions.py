from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()

# where to redirect if user is not logged in
login_manager.login_view = "auth.login"
