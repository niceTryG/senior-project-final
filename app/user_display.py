from __future__ import annotations

from typing import Any


def display_value(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback

    if isinstance(value, str):
        text = value.strip()
        return text or fallback

    text = str(value).strip()
    return text or fallback


def get_user_display_name(user: Any, fallback: str = "User") -> str:
    full_name = display_value(getattr(user, "full_name", None), fallback="")
    if full_name:
        return full_name

    username = display_value(getattr(user, "username", None), fallback="")
    if username:
        return username

    return fallback


def get_user_initials(user: Any, fallback: str = "U") -> str:
    raw_name = get_user_display_name(user, fallback=fallback)
    tokens = [
        "".join(ch for ch in part if ch.isalnum())
        for part in raw_name.replace("_", " ").replace("-", " ").split()
    ]
    tokens = [token for token in tokens if token]

    if len(tokens) >= 2:
        initials = f"{tokens[0][0]}{tokens[1][0]}"
    elif tokens:
        initials = tokens[0][:2]
    else:
        initials = fallback

    return initials.upper()


def get_workspace_name(user: Any, fallback: str = "Workspace") -> str:
    factory = getattr(user, "factory", None)
    if factory:
        return display_value(getattr(factory, "name", None), fallback=fallback)

    shop = getattr(user, "shop", None)
    shop_factory = getattr(shop, "factory", None) if shop else None
    if shop_factory:
        return display_value(getattr(shop_factory, "name", None), fallback=fallback)

    return fallback
