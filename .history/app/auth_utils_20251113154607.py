from functools import wraps
from flask_login import current_user
from flask import abort


def roles_required(*roles):
    """
    Usage:
        @login_required
        @roles_required("admin", "manager")
        def some_view():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return func(*args, **kwargs)
        return wrapper
    return decorator
