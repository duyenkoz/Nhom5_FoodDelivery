from app.extensions import db
from app.utils.time_utils import vietnam_now


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    setting_key = db.Column(db.String(100), primary_key=True)
    setting_value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=vietnam_now, onupdate=vietnam_now)
