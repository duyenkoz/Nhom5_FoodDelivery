from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Order, OrderItem
from app.services.location_service import normalize_text
from app.services.restaurant_service import infer_category, infer_image_path
from app.utils.time_utils import vietnam_now


RECOMMENDATION_LIMIT = 6
RECENT_ORDER_LIMIT = 12
RECENT_DAYS_WINDOW = 90


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format_price(value):
    if value is None:
        return "Liên hệ"
    return f"{int(value):,}".replace(",", ".") + "đ"


def _normalize_image_path(image_value):
    image_value = _clean(image_value)
    if not image_value:
        return "images/restaurant-default.svg"
    if image_value.startswith("/static/"):
        return image_value[len("/static/") :]
    if image_value.startswith("/"):
        return image_value.lstrip("/")
    if image_value.startswith(("http://", "https://")):
        return image_value
    if "/" in image_value:
        return image_value
    return f"uploads/{image_value}"


def _image_url(image_path):
    if not image_path:
        return ""
    image_path = image_path.strip()
    if not image_path:
        return ""
    if image_path.startswith(("http://", "https://", "/")):
        return image_path
    if "/" in image_path:
        return f"/static/{image_path}"
    return f"/static/uploads/{image_path}"


def _slugify(value):
    return normalize_text(value or "")


def _dish_text(dish):
    return _slugify(" ".join([dish.dish_name or "", dish.description or "", dish.category or ""]))


def _dish_type(dish):
    text = _dish_text(dish)
    if any(keyword in text for keyword in ("tra sua", "tra", "nuoc", "coffee", "cafe", "sua chua", "soda")):
        return "drink"
    if any(keyword in text for keyword in ("che", "kem", "dessert", "banh ngot", "sua chua")):
        return "dessert"
    if any(keyword in text for keyword in ("gio", "cha gio", "salad", "khoai", "khai vi", "snack")):
        return "side"
    if any(keyword in text for keyword in ("combo", "set", "phan", "suat")):
        return "combo"
    return "main"


def _meal_slot():
    hour = vietnam_now().hour
    if 5 <= hour < 10:
        return "breakfast"
    if 10 <= hour < 14:
        return "lunch"
    if 14 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "dinner"
    return "late"


def _time_slot_boost(dish):
    dish_type = _dish_type(dish)
    slot = _meal_slot()
    if slot == "breakfast":
        if dish_type in {"drink", "main"}:
            return 6, "Phù hợp bữa sáng"
    elif slot == "lunch":
        if dish_type in {"main", "combo"}:
            return 6, "Phù hợp bữa trưa"
    elif slot == "afternoon":
        if dish_type in {"drink", "dessert", "side"}:
            return 6, "Hợp ăn xế"
    elif slot == "dinner":
        if dish_type in {"main", "combo", "side"}:
            return 6, "Phù hợp bữa tối"
    elif dish_type in {"drink", "dessert"}:
        return 4, "Hợp ăn khuya"
    return 0, ""


def _build_cart_signals(cart_items):
    cart_dish_ids = set()
    cart_categories = Counter()
    cart_prices = []

    for item in cart_items or []:
        dish_id = _safe_int(item.get("dish_id"))
        if dish_id:
            cart_dish_ids.add(dish_id)
        category = _clean(item.get("category"))
        if category:
            cart_categories[_slugify(category)] += 1
        price = _safe_int(item.get("price"), 0)
        if price > 0:
            cart_prices.append(price)

    return {
        "dish_ids": cart_dish_ids,
        "categories": cart_categories,
        "average_price": int(sum(cart_prices) / len(cart_prices)) if cart_prices else 0,
    }


def _recent_customer_orders(user_id, restaurant_id):
    if not user_id:
        return []

    cutoff = datetime.utcnow() - timedelta(days=RECENT_DAYS_WINDOW)
    return (
        Order.query.options(joinedload(Order.items).joinedload(OrderItem.dish))
        .filter(Order.customer_id == user_id, Order.restaurant_id == restaurant_id)
        .filter(Order.order_date.isnot(None))
        .filter(Order.order_date >= cutoff)
        .order_by(Order.order_date.desc(), Order.order_id.desc())
        .limit(RECENT_ORDER_LIMIT)
        .all()
    )


def _load_sold_counts(restaurant_id):
    rows = (
        db.session.query(
            OrderItem.dish_id.label("dish_id"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("sold_count"),
        )
        .join(Order, Order.order_id == OrderItem.order_id)
        .filter(Order.restaurant_id == restaurant_id)
        .group_by(OrderItem.dish_id)
        .all()
    )
    return {row.dish_id: _safe_int(row.sold_count, 0) for row in rows if row.dish_id is not None}


def _load_current_restaurant_dishes(restaurant):
    return [
        dish
        for dish in (restaurant.dishes or [])
        if getattr(dish, "status", False)
    ]


def _build_cooccurrence_map(recent_orders, seed_dish_ids):
    cooccurrence = Counter()
    category_counts = Counter()
    favorite_dishes = Counter()

    for order in recent_orders or []:
        order_dish_ids = []
        for item in order.items or []:
            if not item.dish or not getattr(item.dish, "status", False):
                continue
            dish_id = _safe_int(item.dish_id)
            if not dish_id:
                continue
            order_dish_ids.append(dish_id)
            if dish_id in seed_dish_ids:
                continue
            favorite_dishes[dish_id] += _safe_int(item.quantity, 1)
            category = _clean(getattr(item.dish, "category", ""))
            if category:
                category_counts[_slugify(category)] += 1

        if not order_dish_ids:
            continue

        seed_hits = seed_dish_ids.intersection(order_dish_ids)
        if not seed_hits:
            continue

        for dish_id in order_dish_ids:
            if dish_id in seed_dish_ids:
                continue
            cooccurrence[dish_id] += len(seed_hits)

    return cooccurrence, category_counts, favorite_dishes


def _pick_reason(reasons):
    if not reasons:
        return ""
    reasons.sort(key=lambda item: (-item[0], item[1]))
    labels = []
    for _score, label in reasons:
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= 2:
            break
    return " · ".join(labels)


def get_checkout_recommendations(restaurant, cart_items, user_id=None, customer_profile=None, delivery_distance_km=None, limit=RECOMMENDATION_LIMIT):
    if not restaurant:
        return []

    dishes = _load_current_restaurant_dishes(restaurant)
    if not dishes:
        return []

    cart_signals = _build_cart_signals(cart_items)
    seed_dish_ids = set(cart_signals["dish_ids"])
    recent_orders = _recent_customer_orders(user_id, restaurant.restaurant_id)
    cooccurrence, recent_category_counts, favorite_dishes = _build_cooccurrence_map(recent_orders, seed_dish_ids)
    sold_counts = _load_sold_counts(restaurant.restaurant_id)

    recent_history_categories = Counter()
    for order in recent_orders or []:
        for item in order.items or []:
            category = _clean(getattr(item.dish, "category", "")) if item.dish else ""
            if category:
                recent_history_categories[_slugify(category)] += 1

    scores = []
    for dish in dishes:
        if dish.dish_id in seed_dish_ids:
            continue

        score = 0.0
        reasons = []
        dish_category = _clean(dish.category) or _clean(infer_category(dish))
        dish_category_key = _slugify(dish_category)
        dish_type = _dish_type(dish)
        dish_price = _safe_int(dish.price, 0)
        sold_count = sold_counts.get(dish.dish_id, 0)

        if dish_category_key and cart_signals["categories"].get(dish_category_key):
            boost = 20 + cart_signals["categories"][dish_category_key] * 4
            score += boost
            reasons.append((boost, "Cùng nhóm món"))

        if recent_category_counts.get(dish_category_key):
            boost = 10 + recent_category_counts[dish_category_key] * 2
            score += boost
            reasons.append((boost, "Bạn hay đặt"))

        if favorite_dishes.get(dish.dish_id):
            boost = 28 + favorite_dishes[dish.dish_id] * 4
            score += boost
            reasons.append((boost, "Từng đặt gần đây"))

        if cooccurrence.get(dish.dish_id):
            boost = 24 + cooccurrence[dish.dish_id] * 5
            score += boost
            reasons.append((boost, "Thường mua kèm"))

        if sold_count:
            boost = min(14, sold_count * 1.2)
            score += boost
            reasons.append((boost, "Bán chạy"))

        time_boost, time_reason = _time_slot_boost(dish)
        if time_boost:
            score += time_boost
            reasons.append((time_boost, time_reason))

        if cart_signals["average_price"]:
            avg_price = cart_signals["average_price"]
            if avg_price and 0.7 * avg_price <= dish_price <= 1.4 * avg_price:
                score += 4
                reasons.append((4, "Mức giá tương tự"))

        if delivery_distance_km is not None:
            if delivery_distance_km >= 5 and dish_type in {"drink", "dessert", "side"} and dish_price <= max(25000, cart_signals["average_price"] or 40000):
                score += 3
                reasons.append((3, "Dễ thêm vào đơn"))
            elif delivery_distance_km < 5 and sold_count:
                score += 2
                reasons.append((2, "Phù hợp khu vực giao"))

        if customer_profile and customer_profile.area:
            score += 0.5

        if not reasons:
            continue

        scores.append(
            {
                "dish_id": dish.dish_id,
                "restaurant_id": dish.restaurant_id,
                "name": dish.dish_name or "Món ăn",
                "description": _clean(dish.description) or "Món ăn gợi ý thêm cho đơn hàng.",
                "price": dish_price,
                "price_text": _format_price(dish_price),
                "category": dish_category,
                "image_path": _normalize_image_path(dish.image or infer_image_path(dish_category, dish)),
                "image_url": _image_url(_normalize_image_path(dish.image or infer_image_path(dish_category, dish))),
                "reason": _pick_reason(reasons),
                "score": round(score, 2),
            }
        )

    scores.sort(key=lambda item: (-item["score"], item["price"], item["dish_id"]))
    return scores[:limit]
