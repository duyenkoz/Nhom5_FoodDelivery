from functools import lru_cache

from app.extensions import db
from app.models.system_setting import SystemSetting


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _cast_setting_value(raw_value, default):
    if raw_value in (None, ""):
        return default
    if default is None:
        return raw_value
    if isinstance(default, bool):
        return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(float(raw_value))
        except (TypeError, ValueError):
            return default
    if isinstance(default, float):
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return default
    return raw_value


@lru_cache(maxsize=128)
def _get_setting_raw(setting_key):
    key = _clean(setting_key)
    if not key:
        return None

    setting = db.session.get(SystemSetting, key)
    return setting.setting_value if setting else None


def get_setting(setting_key, default=None):
    return _cast_setting_value(_get_setting_raw(_clean(setting_key)), default)


def set_setting(setting_key, value):
    key = _clean(setting_key)
    if not key:
        raise ValueError("Setting key is required.")

    setting = db.session.get(SystemSetting, key)
    setting_value = "" if value is None else str(value).strip()
    if setting is None:
        setting = SystemSetting(setting_key=key, setting_value=setting_value)
        db.session.add(setting)
    else:
        setting.setting_value = setting_value

    db.session.commit()
    _get_setting_raw.cache_clear()
    return setting


def get_search_radius_km(default=5.0):
    radius = get_setting("SEARCH_RADIUS_KM", default=default)
    try:
        return max(0.0, float(radius))
    except (TypeError, ValueError):
        return float(default)
