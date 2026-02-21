from functools import wraps
from flask_login import current_user
from flask import abort

def roles_required(*roles):
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


def factory_required(func):
    """
    Blocks access if user tries to enter a resource that doesn't belong
    to their assigned factory, unless superadmin.
    Use AFTER login_required.

    Example:
        @login_required
        @factory_required
        def view():
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # superadmin bypass
        if current_user.role == "admin" and current_user.factory_id is None:
            return func(*args, **kwargs)

        # get factory from URL params OR form if sent
        target_factory = request.view_args.get("factory_id") \
                        or request.form.get("factory_id") \
                        or request.args.get("factory_id")

        if target_factory:
            try:
                target_factory = int(target_factory)
            except ValueError:
                abort(400)

            if target_factory != current_user.factory_id:
                abort(403)

        return func(*args, **kwargs)
    return wrapper
