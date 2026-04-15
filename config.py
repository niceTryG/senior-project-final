import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_local_env() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _database_url() -> str:
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql://", 1)
    return raw or f"sqlite:///{BASE_DIR / 'fabric.db'}"


_load_local_env()


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or str(BASE_DIR / "app" / "static" / "uploads" / "products")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = (os.environ.get("SESSION_COOKIE_SAMESITE") or "Lax").strip() or "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)

    REMEMBER_COOKIE_SECURE = _env_bool("REMEMBER_COOKIE_SECURE", False)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    AUTO_DB_BOOTSTRAP = _env_bool("AUTO_DB_BOOTSTRAP", True)
    PROD_ALLOW_SQLITE = _env_bool("PROD_ALLOW_SQLITE", False)

    PUBLIC_TELEGRAM_URL = os.environ.get(
        "PUBLIC_TELEGRAM_URL",
        "https://t.me/ibrohim_musakhodjaev",
    )
    PUBLIC_TELEGRAM_BOT_URL = os.environ.get(
        "PUBLIC_TELEGRAM_BOT_URL",
        "https://t.me/minimoda_sklad_bot",
    )
    GARMENT_AI_WEIGHTS = os.environ.get("GARMENT_AI_WEIGHTS") or str(BASE_DIR / "training" / "weights" / "best.pt")
    GARMENT_AI_DEVICE = os.environ.get("GARMENT_AI_DEVICE") or "cpu"
    GARMENT_AI_CONFIDENCE = float(os.environ.get("GARMENT_AI_CONFIDENCE") or "0.25")


class DevConfig(BaseConfig):
    DEBUG = True
    # Local dev is often accessed over http://127.0.0.1 or a LAN IP from a phone.
    # Secure cookies break session persistence in that setup, so keep them off here.
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    AUTO_DB_BOOTSTRAP = _env_bool("AUTO_DB_BOOTSTRAP", True)


class ProdConfig(BaseConfig):
    DEBUG = False
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or "/opt/render/project/src/uploads"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    REMEMBER_COOKIE_SECURE = _env_bool("REMEMBER_COOKIE_SECURE", True)
    AUTO_DB_BOOTSTRAP = _env_bool("AUTO_DB_BOOTSTRAP", False)
