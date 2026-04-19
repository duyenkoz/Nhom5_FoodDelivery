from datetime import date, datetime, timedelta, timezone


# Use a fixed UTC+7 offset so the app works on Windows machines that do not
# have the tzdata package installed. Vietnam does not observe DST.
VIETNAM_TZ = timezone(timedelta(hours=7))


def _as_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=VIETNAM_TZ)
    return None


def to_vietnam_datetime(value):
    dt = _as_datetime(value)
    if dt is None:
        return None
    return dt.astimezone(VIETNAM_TZ)


def format_vietnam_datetime(value, fmt="%d/%m/%Y %H:%M"):
    dt = to_vietnam_datetime(value)
    return dt.strftime(fmt) if dt else ""


def format_vietnam_date(value, fmt="%d/%m/%Y"):
    dt = to_vietnam_datetime(value)
    return dt.strftime(fmt) if dt else ""


def vietnam_now():
    return datetime.now(VIETNAM_TZ)


def vietnam_today():
    return vietnam_now().date()
