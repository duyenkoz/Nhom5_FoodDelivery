from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Order, OrderItem, Voucher
from app.services.location_service import location_sort_key, normalize_text
from app.utils.time_utils import to_vietnam_datetime, vietnam_now, vietnam_today


SUGGESTION_LIMIT = 8
RECENT_DAYS_WINDOW = 90
COMPLETED_ORDER_STATUSES = {"completed", "delivered", "done"}
PREFERENCE_TAGS = {"drink", "snack", "main", "combo", "breakfast", "lunch", "afternoon", "dinner", "late_night"}

DRINK_KEYWORDS = (
    "do uong",
    "nuoc",
    "tra",
    "tra sua",
    "tra dao",
    "tra tac",
    "coffee",
    "cafe",
    "ca phe",
    "bac xiu",
    "soda",
    "smoothie",
    "juice",
)
SNACK_KEYWORDS = (
    "an vat",
    "khai vi",
    "mon an nhe",
    "trang mieng",
    "dessert",
    "banh",
    "che",
    "snack",
    "salad",
    "khoai",
    "cha gio",
    "nem ran",
)
COMBO_KEYWORDS = ("combo", "set", "phan", "suat")
BREAKFAST_KEYWORDS = (
    "banh mi",
    "pho",
    "bun bo",
    "bun rieu",
    "mi quang",
    "hu tieu",
    "xoi",
    "op la",
    "ca phe",
    "coffee",
    "cafe",
    "bac xiu",
)
LUNCH_KEYWORDS = ("com", "mon chinh", "combo", "pizza", "burger", "bun", "pho", "mi y", "sushi", "ga ran")
AFTERNOON_KEYWORDS = ("do uong", "an vat", "khai vi", "mon an nhe", "dessert", "banh", "tra sua", "tra", "nuoc")
DINNER_KEYWORDS = ("mon chinh", "combo", "lau", "pizza", "burger", "sushi", "com", "bun", "pho", "mi y", "ga ran")
LATE_NIGHT_KEYWORDS = ("do uong", "an vat", "mon an nhe", "dessert", "banh", "tra sua", "tra", "nuoc", "coffee", "cafe")

TIME_SLOT_TAG_WEIGHTS = {
    "breakfast": {"breakfast": 18, "main": 6, "drink": 4},
    "lunch": {"lunch": 18, "main": 12, "combo": 8},
    "afternoon": {"afternoon": 18, "drink": 12, "snack": 10},
    "dinner": {"dinner": 18, "main": 12, "combo": 10, "drink": 4},
    "late_night": {"late_night": 18, "drink": 12, "snack": 10},
}


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _order_status_key(value):
    return normalize_text(value or "")


def _is_completed_status(value):
    return _order_status_key(value) in COMPLETED_ORDER_STATUSES


def _meal_slot_for_datetime(value=None):
    dt = to_vietnam_datetime(value) or vietnam_now()
    hour = dt.hour
    if 5 <= hour < 10:
        return "breakfast"
    if 10 <= hour < 14:
        return "lunch"
    if 14 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "dinner"
    return "late_night"


def _dish_text(dish):
    if not dish:
        return ""
    return normalize_text(" ".join([getattr(dish, "dish_name", ""), getattr(dish, "category", ""), getattr(dish, "description", "")]))


def _dish_category_key(dish):
    category = normalize_text(getattr(dish, "category", "") if dish else "")
    if category:
        return category

    tags = _infer_dish_tags(dish)
    for tag in ("drink", "snack", "combo", "main"):
        if tag in tags:
            return tag
    return ""


def _infer_dish_tags(dish):
    text = _dish_text(dish)
    tags = set()
    if not text:
        return tags

    if any(keyword in text for keyword in DRINK_KEYWORDS):
        tags.update({"drink", "afternoon", "late_night"})
    if any(keyword in text for keyword in SNACK_KEYWORDS):
        tags.update({"snack", "afternoon", "late_night"})
    if any(keyword in text for keyword in COMBO_KEYWORDS):
        tags.update({"combo", "main", "lunch", "dinner"})
    if any(keyword in text for keyword in BREAKFAST_KEYWORDS):
        tags.update({"breakfast", "main"})
    if any(keyword in text for keyword in LUNCH_KEYWORDS):
        tags.update({"lunch", "main"})
    if any(keyword in text for keyword in AFTERNOON_KEYWORDS):
        tags.add("afternoon")
    if any(keyword in text for keyword in DINNER_KEYWORDS):
        tags.update({"dinner", "main"})
    if any(keyword in text for keyword in LATE_NIGHT_KEYWORDS):
        tags.add("late_night")

    if not tags:
        tags.add("main")
    return tags


def _empty_history_profile():
    return {
        "restaurant_order_counts": Counter(),
        "restaurant_slot_counts": defaultdict(Counter),
        "latest_restaurant_order_at": {},
        "category_counts": Counter(),
        "slot_category_counts": defaultdict(Counter),
        "tag_counts": Counter(),
        "slot_tag_counts": defaultdict(Counter),
        "has_history": False,
    }


def _build_user_history_profile(orders):
    profile = _empty_history_profile()
    for order in orders or []:
        if not _is_completed_status(getattr(order, "status", "")):
            continue

        restaurant_id = _safe_int(getattr(order, "restaurant_id", None), 0)
        order_dt = to_vietnam_datetime(getattr(order, "order_date", None)) or vietnam_now()
        slot = _meal_slot_for_datetime(order_dt)

        if restaurant_id:
            profile["restaurant_order_counts"][restaurant_id] += 1
            profile["restaurant_slot_counts"][slot][restaurant_id] += 1
            latest_seen = profile["latest_restaurant_order_at"].get(restaurant_id)
            if latest_seen is None or order_dt > latest_seen:
                profile["latest_restaurant_order_at"][restaurant_id] = order_dt

        for item in getattr(order, "items", []) or []:
            dish = getattr(item, "dish", None)
            if not dish:
                continue

            quantity = max(1, _safe_int(getattr(item, "quantity", 1), 1))
            category_key = _dish_category_key(dish)
            if category_key:
                profile["category_counts"][category_key] += quantity
                profile["slot_category_counts"][slot][category_key] += quantity

            for tag in _infer_dish_tags(dish):
                profile["tag_counts"][tag] += quantity
                profile["slot_tag_counts"][slot][tag] += quantity

    profile["has_history"] = bool(
        profile["restaurant_order_counts"] or profile["category_counts"] or profile["tag_counts"]
    )
    return profile


def _load_recent_customer_orders(customer_id):
    if not customer_id:
        return []

    cutoff = vietnam_now() - timedelta(days=RECENT_DAYS_WINDOW)
    return (
        Order.query.options(joinedload(Order.items).joinedload(OrderItem.dish))
        .filter(Order.customer_id == customer_id)
        .filter(Order.order_date.isnot(None))
        .filter(Order.order_date >= cutoff)
        .order_by(Order.order_date.desc(), Order.order_id.desc())
        .limit(60)
        .all()
    )


def _load_restaurant_popularity(candidate_ids):
    candidate_ids = [candidate_id for candidate_id in candidate_ids if candidate_id]
    if not candidate_ids:
        return {}

    rows = (
        db.session.query(
            Order.restaurant_id.label("restaurant_id"),
            func.count(func.distinct(Order.order_id)).label("completed_orders"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("sold_quantity"),
        )
        .join(OrderItem, OrderItem.order_id == Order.order_id)
        .filter(Order.restaurant_id.in_(candidate_ids))
        .filter(func.lower(func.coalesce(Order.status, "")).in_(tuple(COMPLETED_ORDER_STATUSES)))
        .group_by(Order.restaurant_id)
        .all()
    )

    raw_scores = {}
    for row in rows:
        completed_orders = _safe_int(row.completed_orders, 0)
        sold_quantity = _safe_int(row.sold_quantity, 0)
        raw_scores[row.restaurant_id] = completed_orders * 6 + sold_quantity

    max_score = max(raw_scores.values()) if raw_scores else 0
    if max_score <= 0:
        return {}

    return {
        restaurant_id: round((score / max_score) * 20, 2)
        for restaurant_id, score in raw_scores.items()
    }


def _load_active_promotion_map(candidate_ids):
    candidate_ids = {candidate_id for candidate_id in candidate_ids if candidate_id}
    if not candidate_ids:
        return {}

    today = vietnam_today()
    vouchers = (
        Voucher.query.filter(Voucher.status.is_(True))
        .filter(Voucher.voucher_scope == "restaurant")
        .filter(or_(Voucher.created_by.in_(candidate_ids), Voucher.created_by.is_(None)))
        .all()
    )

    promotion_map = {candidate_id: False for candidate_id in candidate_ids}
    for voucher in vouchers:
        if voucher.start_date and voucher.start_date > today:
            continue
        if voucher.end_date and voucher.end_date < today:
            continue

        if voucher.created_by is None:
            for candidate_id in candidate_ids:
                promotion_map[candidate_id] = True
            continue

        restaurant_id = _safe_int(voucher.created_by, 0)
        if restaurant_id in promotion_map:
            promotion_map[restaurant_id] = True

    return promotion_map


def _restaurant_history_score(restaurant_id, history_profile, slot, now=None):
    order_count = history_profile["restaurant_order_counts"].get(restaurant_id, 0)
    slot_order_count = history_profile["restaurant_slot_counts"][slot].get(restaurant_id, 0)
    if not order_count and not slot_order_count:
        return 0.0

    score = min(36, order_count * 10) + min(12, slot_order_count * 6)
    latest_order_at = history_profile["latest_restaurant_order_at"].get(restaurant_id)
    if latest_order_at is not None:
        current_dt = to_vietnam_datetime(now) or vietnam_now()
        delta_days = max(0, (current_dt - latest_order_at).days)
        if delta_days <= 7:
            score += 14
        elif delta_days <= 30:
            score += 8
        elif delta_days <= 90:
            score += 4

    return round(score, 2)


def _best_dish_time_match_score(dishes, slot):
    slot_weights = TIME_SLOT_TAG_WEIGHTS.get(slot, {})
    best_score = 0
    for dish in dishes:
        tags = _infer_dish_tags(dish)
        dish_score = sum(slot_weights.get(tag, 0) for tag in tags)
        if dish_score > best_score:
            best_score = dish_score
    return round(float(best_score), 2)


def _category_preference_score(dishes, history_profile, slot):
    if not history_profile.get("has_history"):
        return 0.0

    score = 0.0
    seen_categories = set()
    seen_tags = set()

    for dish in dishes:
        category_key = _dish_category_key(dish)
        if category_key and category_key not in seen_categories:
            score += min(16, history_profile["slot_category_counts"][slot].get(category_key, 0) * 4)
            score += min(10, history_profile["category_counts"].get(category_key, 0) * 1.5)
            seen_categories.add(category_key)

        for tag in _infer_dish_tags(dish):
            if tag not in PREFERENCE_TAGS or tag in seen_tags:
                continue
            score += min(8, history_profile["slot_tag_counts"][slot].get(tag, 0) * 2.5)
            score += min(5, history_profile["tag_counts"].get(tag, 0) * 1.2)
            seen_tags.add(tag)

    return round(min(score, 40), 2)


def _promotion_score(restaurant_id, promotion_map):
    return 10.0 if promotion_map.get(restaurant_id) else 0.0


def _rank_candidate_restaurants(payloads, history_profile, popularity_map, promotion_map, slot, now=None):
    ranked_items = []
    for payload in payloads or []:
        restaurant = payload.get("restaurant")
        if not restaurant:
            continue

        active_dishes = [dish for dish in (restaurant.dishes or []) if getattr(dish, "status", False)]
        if not active_dishes:
            continue

        restaurant_id = restaurant.restaurant_id
        history_score = _restaurant_history_score(restaurant_id, history_profile, slot, now=now)
        time_score = _best_dish_time_match_score(active_dishes, slot)
        category_score = _category_preference_score(active_dishes, history_profile, slot)
        popularity_score = float(popularity_map.get(restaurant_id, 0.0))
        promotion_score = _promotion_score(restaurant_id, promotion_map)
        total_score = round(history_score + time_score + category_score + popularity_score + promotion_score, 2)

        ranked_items.append(
            {
                "restaurant_id": restaurant_id,
                "score": total_score,
                "active_dish_count": len(active_dishes),
                "distance_km": payload.get("distance_km"),
            }
        )

    ranked_items.sort(
        key=lambda item: (
            -item["score"],
            -item["active_dish_count"],
            location_sort_key(item["distance_km"], item["restaurant_id"]),
        )
    )
    return [item["restaurant_id"] for item in ranked_items]


def get_personalized_suggested_restaurant_ids(customer_id, payloads, limit=SUGGESTION_LIMIT, now=None):
    customer_id = _safe_int(customer_id, 0)
    if not customer_id:
        return []

    candidate_payloads = [payload for payload in (payloads or []) if payload.get("active_dish_count", 0) > 0]
    if not candidate_payloads:
        return []

    recent_orders = _load_recent_customer_orders(customer_id)
    history_profile = _build_user_history_profile(recent_orders)
    candidate_ids = [payload["restaurant"].restaurant_id for payload in candidate_payloads if payload.get("restaurant")]
    popularity_map = _load_restaurant_popularity(candidate_ids)
    promotion_map = _load_active_promotion_map(candidate_ids)
    slot = _meal_slot_for_datetime(now)
    ranked_ids = _rank_candidate_restaurants(
        candidate_payloads,
        history_profile,
        popularity_map,
        promotion_map,
        slot,
        now=now,
    )
    return ranked_ids[: max(1, _safe_int(limit, SUGGESTION_LIMIT))]
