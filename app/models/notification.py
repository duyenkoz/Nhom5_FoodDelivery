from datetime import datetime

from app.extensions import db


class Notification(db.Model):
    __tablename__ = "notifications"

    notification_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=False, index=True)
    type = db.Column(db.String(50), nullable=True)
    title = db.Column(db.String(120), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=True)
    payload_json = db.Column(db.Text, nullable=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", back_populates="notifications")
