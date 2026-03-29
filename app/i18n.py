from flask import request, session

try:
    from flask_login import current_user
except Exception:
    current_user = None


SUPPORTED_LANGUAGES = ("ru", "en", "uz")
DEFAULT_LANGUAGE = "ru"


def select_locale():
    """
    Language priority:
    1) saved user preference in DB, if you add user.language later
    2) session["lang"]
    3) browser Accept-Language
    4) DEFAULT_LANGUAGE
    """

    # 1. user preference from database
    if current_user is not None:
        try:
            if getattr(current_user, "is_authenticated", False):
                user_lang = getattr(current_user, "language", None)
                if user_lang in SUPPORTED_LANGUAGES:
                    return user_lang
        except Exception:
            pass

    # 2. language saved in session
    session_lang = session.get("lang")
    if session_lang in SUPPORTED_LANGUAGES:
        return session_lang

    # 3. browser language
    best = request.accept_languages.best_match(SUPPORTED_LANGUAGES)
    if best in SUPPORTED_LANGUAGES:
        return best

    # 4. fallback
    return DEFAULT_LANGUAGE