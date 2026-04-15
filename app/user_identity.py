from __future__ import annotations

import re


def normalize_phone(value) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    has_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None

    return f"+{digits}" if has_plus else digits


def normalize_username(value) -> str:
    return str(value or "").strip()


def build_login_username(username_value, phone_value) -> str:
    username = normalize_username(username_value)
    if username:
        return username

    return normalize_phone(phone_value) or ""
