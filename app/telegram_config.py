import os
from pathlib import Path


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
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


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default

    try:
        return int(raw)
    except ValueError:
        return default


def _env_chat_ids(name: str) -> list[int]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return []

    chat_ids: list[int] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue

        try:
            chat_ids.append(int(item))
        except ValueError:
            continue

    return chat_ids


_load_local_env()

TELEGRAM_BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
MANAGER_CHAT_IDS = _env_chat_ids("MANAGER_CHAT_IDS")
DEFAULT_FACTORY_ID = _env_int("DEFAULT_FACTORY_ID", 1)
LOW_STOCK_THRESHOLD = _env_int("LOW_STOCK_THRESHOLD", 5)
DEFAULT_CASH_CURRENCY = (os.environ.get("DEFAULT_CASH_CURRENCY") or "UZS").strip().upper() or "UZS"
