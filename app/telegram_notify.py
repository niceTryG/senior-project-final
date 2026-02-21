import requests
from app.telegram_config import TELEGRAM_BOT_TOKEN, MANAGER_CHAT_IDS

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def send_telegram_message(text: str, chat_ids: list[int] | None = None) -> None:
    """
    Simple helper: send text to all manager chat IDs.
    Ошибки мы глушим, чтобы не ломать Flask, если телега недоступна.
    """
    if not TELEGRAM_BOT_TOKEN:
        return  # бот не настроен

    if chat_ids is None:
        chat_ids = MANAGER_CHAT_IDS

    for chat_id in chat_ids:
        if not chat_id:
            continue
        try:
            requests.post(
                API_URL,
                data={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
                timeout=3,
            )
        except Exception:
            # Логировать можно, но не обязательно
            continue
