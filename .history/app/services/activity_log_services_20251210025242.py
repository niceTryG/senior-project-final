# app/services/activity_log_service.py
from app import db
from app.models.activity_log import ActivityLog
from flask import request
from flask_login import current_user

class ActivityLogService:
    @staticmethod
    def log(action, entity, entity_id=None, before=None, after=None, comment=None):
        try:
            entry = ActivityLog(
                user_id=getattr(current_user, "id", None),
                action=action,
                entity=entity,
                entity_id=entity_id,
                before=before,
                after=after,
                ip=request.remote_addr,
                comment=comment
            )
            db.session.add(entry)
            db.session.commit()
        except Exception:
            # NEVER break the UI because logging failed
            db.session.rollback()
            pass

activity_log = ActivityLogService()
