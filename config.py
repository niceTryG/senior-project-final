import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"

    # Render provides DATABASE_URL for Postgres
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(BASE_DIR, "fabric.db")
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # uploads
    UPLOAD_FOLDER = "app/static/uploads/products"
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB

    # 🔐 Session & Login Improvements
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False  # False for LAN / HTTP

    REMEMBER_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = timedelta(days=30)

    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    # Telegram
    PUBLIC_TELEGRAM_URL = os.environ.get(
        "PUBLIC_TELEGRAM_URL",
        "https://t.me/ibrohim_musakhodjaev"
    )


class DevConfig(BaseConfig):
    DEBUG = True


class ProdConfig(BaseConfig):
    DEBUG = False