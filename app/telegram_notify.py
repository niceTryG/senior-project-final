import requests
from app.telegram_config import TELEGRAM_BOT_TOKEN, MANAGER_CHAT_IDS
from app.models import TelegramLink


def _linked_chat_ids_for_factories(factory_ids: list[int] | None) -> list[int]:
    ids = [int(fid) for fid in (factory_ids or []) if fid]
    if not ids:
        return []

    try:
        rows = (
            TelegramLink.query
            .filter(TelegramLink.factory_id.in_(ids))
            .with_entities(TelegramLink.telegram_chat_id)
            .distinct()
            .all()
        )
    except Exception:
        return []

    return [int(chat_id) for (chat_id,) in rows if chat_id]


def send_telegram_message(
    text: str,
    chat_ids: list[int] | None = None,
    disable_preview: bool = True,
    factory_id: int | None = None,
    factory_ids: list[int] | None = None,
    include_manager_chats: bool = True,
) -> None:
    """
    Send Telegram message to manager chats.
    Errors are suppressed so Flask never breaks.
    """

    if not TELEGRAM_BOT_TOKEN:
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    if chat_ids is None:
        resolved_chat_ids: list[int] = []

        if include_manager_chats:
            resolved_chat_ids.extend(MANAGER_CHAT_IDS)

        combined_factory_ids = list(factory_ids or [])
        if factory_id:
            combined_factory_ids.append(factory_id)

        resolved_chat_ids.extend(_linked_chat_ids_for_factories(combined_factory_ids))

        seen: set[int] = set()
        chat_ids = []
        for chat_id in resolved_chat_ids:
            if not chat_id or chat_id in seen:
                continue
            seen.add(chat_id)
            chat_ids.append(chat_id)

    payload = {
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
    }

    for chat_id in chat_ids:
        if not chat_id:
            continue

        try:
            requests.post(
                api_url,
                data={**payload, "chat_id": chat_id},
                timeout=3,
            )
        except Exception:
            continue


def send_telegram_document(
    document_bytes: bytes,
    filename: str,
    *,
    caption: str | None = None,
    chat_ids: list[int] | None = None,
    factory_id: int | None = None,
    factory_ids: list[int] | None = None,
    include_manager_chats: bool = True,
) -> None:
    """
    Send a file to Telegram chats.
    Errors are suppressed so Flask never breaks.
    """

    if not TELEGRAM_BOT_TOKEN or not document_bytes:
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"

    if chat_ids is None:
        resolved_chat_ids: list[int] = []

        if include_manager_chats:
            resolved_chat_ids.extend(MANAGER_CHAT_IDS)

        combined_factory_ids = list(factory_ids or [])
        if factory_id:
            combined_factory_ids.append(factory_id)

        resolved_chat_ids.extend(_linked_chat_ids_for_factories(combined_factory_ids))

        seen: set[int] = set()
        chat_ids = []
        for chat_id in resolved_chat_ids:
            if not chat_id or chat_id in seen:
                continue
            seen.add(chat_id)
            chat_ids.append(chat_id)

    for chat_id in chat_ids:
        if not chat_id:
            continue

        try:
            requests.post(
                api_url,
                data={
                    "chat_id": chat_id,
                    "caption": caption or "",
                    "parse_mode": "HTML",
                },
                files={
                    "document": (filename, document_bytes, "application/pdf"),
                },
                timeout=8,
            )
        except Exception:
            continue
