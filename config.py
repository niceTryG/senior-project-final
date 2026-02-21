import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"

    # Render provides DATABASE_URL for Postgres
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(BASE_DIR, "fabric.db")
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # uploads (kept from your existing config)
    UPLOAD_FOLDER = "app/static/uploads/products"
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB


class DevConfig(BaseConfig):
    DEBUG = True


class ProdConfig(BaseConfig):
    DEBUG = False

    # Secure cookie defaults behind HTTPS (Render)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = True
