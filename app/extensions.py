from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_babel import Babel

try:
    from flask_migrate import Migrate
except ImportError:  # pragma: no cover - optional until env is refreshed
    Migrate = None

db = SQLAlchemy()
login_manager = LoginManager()
babel = Babel()
migrate = Migrate() if Migrate is not None else None
MIGRATE_AVAILABLE = migrate is not None

# where to redirect if user is not logged in
login_manager.login_view = "auth.login"
