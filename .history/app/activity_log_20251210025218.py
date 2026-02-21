# app/models/activity_log.py
from app import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB  # works on postgres, fallback to JSON

class ActivityLog(db.Model):
    __tablename__ = "activity_log"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    action = db.Column(db.String(100), nullable=False)

    entity = db.Column(db.String(100), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)

    before = db.Column(JSONB, nullable=True)
    after = db.Column(JSONB, nullable=True)

    ip = db.Column(db.String(50), nullable=True)
    comment = db.Column(db.Text, nullable=True)
