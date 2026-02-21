# app/utils/log_action.py
from functools import wraps
from services.activity_log_service import activity_log

def log_action(action, entity):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            result = f(*args, **kwargs)

            entity_id = kwargs.get("fabric_id") or kwargs.get("id") or None

            activity_log.log(
                action=action,
                entity=entity,
                entity_id=entity_id,
                after={"success": True}
            )

            return result
        return wrapper
    return decorator
