import json
import os

from flask import current_app


DEFAULT_SHIPPING_RULES = [
    {"min_km": 0, "max_km": 2, "fee": 12000},
    {"min_km": 2, "max_km": 5, "fee": 18000},
    {"min_km": 5, "max_km": 8, "fee": 25000},
    {"min_km": 8, "max_km": 12, "fee": 35000},
    {"min_km": 12, "max_km": None, "fee": 45000},
]

DEFAULT_FEE_SETTINGS = {
    "floor_fee": 15000,
    "rules": DEFAULT_SHIPPING_RULES,
}


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rules_file_path():
    instance_path = getattr(current_app, "instance_path", "")
    if instance_path:
        os.makedirs(instance_path, exist_ok=True)
        return os.path.join(instance_path, "shipping_fee_rules.json")
    return os.path.join(os.getcwd(), "shipping_fee_rules.json")


def _normalize_rule(rule):
    if not isinstance(rule, dict):
        return None

    min_km = rule.get("min_km")
    max_km = rule.get("max_km")
    fee = _safe_int(rule.get("fee"), 0)

    if min_km in (None, ""):
        min_km = 0
    else:
        try:
            min_km = float(min_km)
        except (TypeError, ValueError):
            min_km = 0

    if max_km in (None, ""):
        max_km = None
    else:
        try:
            max_km = float(max_km)
        except (TypeError, ValueError):
            max_km = None

    if max_km is not None and max_km < min_km:
        min_km, max_km = max_km, min_km

    return {
        "min_km": round(float(min_km), 2),
        "max_km": round(float(max_km), 2) if max_km is not None else None,
        "fee": max(0, fee),
    }


def _sort_rules(rules):
    return sorted(rules, key=lambda item: (item["min_km"], item["max_km"] if item["max_km"] is not None else float("inf")))


def _normalize_settings(raw_settings):
    if isinstance(raw_settings, dict):
        raw_rules = raw_settings.get("rules")
        floor_fee = _safe_int(raw_settings.get("floor_fee"), DEFAULT_FEE_SETTINGS["floor_fee"])
    elif isinstance(raw_settings, list):
        raw_rules = raw_settings
        floor_fee = DEFAULT_FEE_SETTINGS["floor_fee"]
    else:
        raw_rules = None
        floor_fee = DEFAULT_FEE_SETTINGS["floor_fee"]

    rules = []
    if isinstance(raw_rules, list):
        for raw_rule in raw_rules:
            normalized = _normalize_rule(raw_rule)
            if normalized is not None:
                rules.append(normalized)

    if not rules:
        rules = list(DEFAULT_SHIPPING_RULES)

    return {
        "floor_fee": max(0, floor_fee),
        "rules": _sort_rules(rules),
    }


def get_shipping_fee_rules():
    return get_shipping_fee_settings()["rules"]


def get_shipping_fee_settings():
    path = _rules_file_path()
    if not os.path.exists(path):
        return dict(DEFAULT_FEE_SETTINGS, rules=list(DEFAULT_SHIPPING_RULES))

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw_settings = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return dict(DEFAULT_FEE_SETTINGS, rules=list(DEFAULT_SHIPPING_RULES))

    return _normalize_settings(raw_settings)


def save_shipping_fee_rules(rules):
    settings = _normalize_settings({"rules": rules, "floor_fee": DEFAULT_FEE_SETTINGS["floor_fee"]})
    return save_shipping_fee_settings(settings)


def save_shipping_fee_settings(settings):
    normalized = _normalize_settings(settings)
    path = _rules_file_path()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(normalized, handle, ensure_ascii=False, indent=2)
    return normalized


def _format_km(value):
    if value is None:
        return ""
    value = float(value)
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def format_shipping_rule_label(rule):
    if not rule:
        return ""
    min_km = _format_km(rule.get("min_km"))
    max_km = _format_km(rule.get("max_km"))
    if max_km:
        return f"{min_km} km - {max_km} km"
    return f"Từ {min_km} km trở lên"


def get_shipping_fee_quote(distance_km):
    try:
        distance_value = float(distance_km)
    except (TypeError, ValueError):
        distance_value = None

    rules = get_shipping_fee_rules()
    if distance_value is None:
        rule = rules[0] if rules else None
        return {
            "distance_km": None,
            "fee": rule["fee"] if rule else 0,
            "rule": rule,
        }

    selected_rule = None
    for rule in rules:
        min_km = float(rule["min_km"])
        max_km = rule["max_km"]
        max_km_value = float(max_km) if max_km is not None else None
        if distance_value >= min_km and (max_km_value is None or distance_value < max_km_value or abs(distance_value - max_km_value) < 1e-9):
            selected_rule = rule
            break

    if not selected_rule and rules:
        selected_rule = rules[-1]

    return {
        "distance_km": distance_value,
        "fee": selected_rule["fee"] if selected_rule else 0,
        "rule": selected_rule,
    }


def build_shipping_rules_form_values():
    settings = get_shipping_fee_settings()
    rules = settings.get("rules") or list(DEFAULT_SHIPPING_RULES)

    return [
        {
            "min_km": rule.get("min_km", 0),
            "max_km": "" if rule.get("max_km") is None else rule.get("max_km"),
            "fee": rule.get("fee", 0),
            "label": format_shipping_rule_label(rule),
        }
        for rule in rules
    ]


def get_shipping_fee_floor():
    return get_shipping_fee_settings().get("floor_fee", DEFAULT_FEE_SETTINGS["floor_fee"])
