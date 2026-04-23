from datetime import datetime

from sqlalchemy.types import DateTime, TypeDecorator

from app.utils.time_utils import VIETNAM_TZ


class VietnamDateTime(TypeDecorator):
    """Store Vietnam local time in DB while keeping aware VN datetimes in Python."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None:
            return value
        return value.astimezone(VIETNAM_TZ).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=VIETNAM_TZ)
        return value.astimezone(VIETNAM_TZ)
