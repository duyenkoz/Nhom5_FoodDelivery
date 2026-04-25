from datetime import datetime, timedelta

from flask import session
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Customer, Dish, Order, Restaurant, Review
from app.models.cart import Cart
from app.models.cart_item import CartItem
from app.models.order_item import OrderItem
from app.services.ai_review_summary_service import get_ai_review_summary_settings
from app.services.location_service import normalize_text
from app.services.restaurant_service import (
    EXCLUDED_ORDER_STATUSES,
    build_dish_view_model,
    infer_category,
    infer_image_path,
)


CART_SESSION_KEY = "fivefood_carts"


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


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


def _restaurant_title(restaurant):
    if restaurant.user and restaurant.user.display_name:
        return restaurant.user.display_name
    if restaurant.user and restaurant.user.username:
        return restaurant.user.username
    return f"Nhà hàng {restaurant.restaurant_id}"


def _format_address(restaurant):
    address = _clean(restaurant.address)
    area = _clean(restaurant.area)
    return ", ".join(part for part in [address, area] if part)


def _slugify(text):
    return normalize_text(text or "")


def _dish_search_text(dish):
    return _slugify(" ".join([dish.dish_name or "", dish.description or "", dish.category or ""]))


def _active_dishes(restaurant):
    return [dish for dish in (restaurant.dishes or []) if getattr(dish, "status", False)]


def _listed_dishes(restaurant):
    return list(restaurant.dishes or [])


def _dish_name_key(dish):
    return _slugify(_clean(dish.dish_name))


def _dish_orders(dish):
    total_quantity = 0
    for item in (dish.order_items or []):
        order = getattr(item, "order", None)
        status = (getattr(order, "status", "") or "").strip().lower()
        if status in EXCLUDED_ORDER_STATUSES:
            continue
        total_quantity += int(item.quantity or 0)
    return total_quantity


def _fallback_image(dish):
    category = dish.category or infer_category(dish)
    return infer_image_path(category, dish)


def _restaurant_cover_image(restaurant, active_dishes=None):
    active_dishes = active_dishes if active_dishes is not None else _active_dishes(restaurant)
    primary_image = restaurant.image or (active_dishes[0].image if active_dishes else "")
    if not primary_image and active_dishes:
        primary_image = _fallback_image(active_dishes[0])
    return _normalize_image_path(primary_image)


def _build_similar_restaurants(restaurant, limit=6):
    base_dishes = _active_dishes(restaurant)
    base_name_keys = {_dish_name_key(dish) for dish in base_dishes if _dish_name_key(dish)}
    base_categories = {_slugify(_clean(dish.category)) for dish in base_dishes if _clean(dish.category)}

    if not base_name_keys and not base_categories:
        return []

    candidates = (
        Restaurant.query.options(joinedload(Restaurant.user), joinedload(Restaurant.dishes))
        .filter(Restaurant.restaurant_id != restaurant.restaurant_id)
        .all()
    )

    scored = []
    for candidate in candidates:
        candidate_dishes = _active_dishes(candidate)
        if not candidate_dishes:
            continue

        candidate_name_map = {}
        for dish in candidate_dishes:
            key = _dish_name_key(dish)
            if key and key not in candidate_name_map:
                candidate_name_map[key] = _clean(dish.dish_name)

        candidate_categories = {
            _slugify(_clean(dish.category)): _clean(dish.category)
            for dish in candidate_dishes
            if _clean(dish.category)
        }

        shared_name_keys = [key for key in candidate_name_map if key in base_name_keys]
        shared_category_keys = [key for key in candidate_categories if key in base_categories]
        if not shared_name_keys and not shared_category_keys:
            continue

        score = len(shared_name_keys) * 5 + len(shared_category_keys) * 2
        scored.append(
            {
                "restaurant_id": candidate.restaurant_id,
                "name": _restaurant_title(candidate),
                "address": _format_address(candidate),
                "image_path": _restaurant_cover_image(candidate, candidate_dishes),
                "shared_dishes": [candidate_name_map[key] for key in shared_name_keys[:3]],
                "shared_categories": [candidate_categories[key] for key in shared_category_keys[:2]],
                "score": score,
            }
        )

    scored.sort(key=lambda item: (-item["score"], item["name"].lower(), item["restaurant_id"]))
    return scored[:limit]


def _safe_user_name(user):
    if not user:
        return "Khách ẩn danh"
    return user.display_name or user.username or "Khách ẩn danh"


def _format_review_count(value):
    count = int(value or 0)
    if count >= 1000:
        formatted = f"{count / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{formatted}k"
    return str(count)


def _build_public_review_summary(restaurant_id):
    row = (
        db.session.query(
            func.avg(Review.rating).label("average_rating"),
            func.count(Review.review_id).label("review_count"),
            func.sum(case((Review.rating >= 4, 1), else_=0)).label("positive_reviews"),
        )
        .filter(Review.restaurant_id == restaurant_id)
        .filter(Review.rating.isnot(None))
        .one()
    )

    review_count = int(row.review_count or 0)
    average_rating = round(float(row.average_rating or 0), 1) if row.average_rating is not None else 0
    positive_reviews = int(row.positive_reviews or 0)
    return {
        "average_rating": average_rating,
        "review_count": review_count,
        "positive_reviews": positive_reviews,
        "average_rating_text": f"{average_rating:.1f}" if review_count else "0.0",
        "review_count_text": _format_review_count(review_count),
        "review_count_label": f"{_format_review_count(review_count)} Đánh giá",
    }


def _build_public_review_items(restaurant_id, limit=10):
    reviews = (
        Review.query.options(selectinload(Review.customer).selectinload(Customer.user))
        .filter(Review.restaurant_id == restaurant_id)
        .order_by(Review.review_date.desc(), Review.review_id.desc())
        .limit(limit)
        .all()
    )

    items = []
    for review in reviews:
        customer_name = "Khách ẩn danh"
        customer_phone = ""
        if review.customer and review.customer.user:
            customer_name = _safe_user_name(review.customer.user)
            customer_phone = review.customer.user.phone or ""

        items.append(
            {
                "review": review,
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "review_date_text": (
                    review.review_date.strftime("%H:%M %d/%m/%Y")
                    if review.review_date
                    else ""
                ),
                "avatar_text": customer_name[:1] if customer_name else "K",
            }
        )
    return items


def get_public_review_summary(restaurant_id):
    return _build_public_review_summary(restaurant_id)


def get_public_restaurant(restaurant_id, include_reviews=False):
    options = [
        joinedload(Restaurant.user),
        joinedload(Restaurant.dishes).joinedload(Dish.order_items).joinedload(OrderItem.order),
    ]

    return Restaurant.query.options(*options).filter(Restaurant.restaurant_id == restaurant_id).one_or_none()


def get_public_dish(restaurant_id, dish_id):
    dish = (
        Dish.query.options(joinedload(Dish.restaurant).joinedload(Restaurant.user))
        .filter(Dish.dish_id == dish_id, Dish.restaurant_id == restaurant_id, Dish.status.is_(True))
        .one_or_none()
    )
    return dish


def _dish_to_view(dish):
    base = build_dish_view_model(dish)
    image_path = base["image_path"] or _fallback_image(dish)
    return {
        "dish_id": dish.dish_id,
        "restaurant_id": dish.restaurant_id,
        "name": dish.dish_name or "Món ăn",
        "description": _clean(dish.description) or "Món ăn đang được cập nhật mô tả.",
        "price": int(dish.price or 0),
        "price_text": _format_price(dish.price),
        "category": dish.category or base["category"],
        "category_slug": _slugify(dish.category or base["category"]),
        "image_path": _normalize_image_path(image_path),
        "sold_count": _dish_orders(dish),
        "search_text": _dish_search_text(dish),
        "is_available": bool(getattr(dish, "status", False)),
    }


def _empty_cart_payload(restaurant_id):
    return {
        "restaurant_id": restaurant_id,
        "cart_id": None,
        "items": [],
        "total_quantity": 0,
        "total_amount": 0,
        "total_amount_text": _format_price(0),
        "is_empty": True,
    }


def _session_user_id(session_obj):
    try:
        return int(session_obj.get("user_id"))
    except (TypeError, ValueError, AttributeError):
        return None


def _is_logged_in_customer(session_obj):
    return (
        session_obj.get("auth_state") == "logged_in"
        and session_obj.get("user_role") == "customer"
        and _session_user_id(session_obj) is not None
    )


def _get_db_cart(session_obj, restaurant_id):
    customer_id = _session_user_id(session_obj)
    if customer_id is None:
        return None
    return (
        Cart.query.filter_by(customer_id=customer_id, restaurant_id=restaurant_id)
        .order_by(Cart.created_at.desc(), Cart.cart_id.desc())
        .first()
    )


def _serialize_db_cart(cart, restaurant_id):
    if not cart:
        return _empty_cart_payload(restaurant_id)

    payload_items = []
    total_quantity = 0
    total_amount = 0
    for cart_item in sorted(cart.items or [], key=lambda item: item.cart_item_id or 0):
        dish = cart_item.dish
        if not dish or not dish.status:
            continue
        quantity = max(1, int(cart_item.quantity or 1))
        price = int(cart_item.price if cart_item.price is not None else dish.price or 0)
        line_total = price * quantity
        total_quantity += quantity
        total_amount += line_total
        payload_items.append(
            {
                "dish_id": dish.dish_id,
                "name": dish.dish_name or "Món ăn",
                "price": price,
                "price_text": _format_price(price),
                "quantity": quantity,
                "note": _clean(getattr(cart_item, "note", "")),
                "line_total": line_total,
                "line_total_text": _format_price(line_total),
                "image_path": _normalize_image_path(dish.image or _fallback_image(dish)),
            }
        )

    payload_items.sort(key=lambda item: (item["name"].lower(), item["dish_id"]))

    return {
        "restaurant_id": restaurant_id,
        "cart_id": cart.cart_id,
        "items": payload_items,
        "total_quantity": total_quantity,
        "total_amount": total_amount,
        "total_amount_text": _format_price(total_amount),
        "is_empty": not payload_items,
    }


def _ensure_cart_root(session):
    carts = session.get(CART_SESSION_KEY)
    if not isinstance(carts, dict):
        carts = {}
        session[CART_SESSION_KEY] = carts
    return carts


def _ensure_restaurant_cart(session, restaurant_id):
    carts = _ensure_cart_root(session)
    restaurant_key = str(restaurant_id)
    cart = carts.get(restaurant_key)
    if not isinstance(cart, dict):
        cart = {"items": {}}
        carts[restaurant_key] = cart

    items = cart.get("items")
    if not isinstance(items, dict):
        cart["items"] = {}
    return cart


def _prune_empty_restaurant_cart(session, restaurant_id):
    carts = _ensure_cart_root(session)
    restaurant_key = str(restaurant_id)
    cart = carts.get(restaurant_key)
    if isinstance(cart, dict) and not cart.get("items"):
        carts.pop(restaurant_key, None)


def clear_restaurant_cart(session, restaurant_id):
    if restaurant_id in (None, "", 0, "0"):
        return False

    cleared = False

    if _is_logged_in_customer(session):
        customer_id = _session_user_id(session)
        if customer_id is not None:
            cart = _get_db_cart(session, restaurant_id)
            if cart:
                db.session.delete(cart)
                db.session.commit()
                cleared = True

    carts = session.get(CART_SESSION_KEY)
    if isinstance(carts, dict):
        restaurant_key = str(restaurant_id)
        if restaurant_key in carts:
            carts.pop(restaurant_key, None)
            session.modified = True
            cleared = True

    _prune_empty_restaurant_cart(session, restaurant_id)
    return cleared


def migrate_guest_carts_to_logged_in_customer(session):
    if not _is_logged_in_customer(session):
        return False

    carts = session.get(CART_SESSION_KEY)
    if not isinstance(carts, dict) or not carts:
        return False

    customer_id = _session_user_id(session)
    if customer_id is None:
        return False

    migrated = False
    restaurant_ids_to_clear = []

    for restaurant_key, cart_state in list(carts.items()):
        if not isinstance(cart_state, dict):
            continue

        items = cart_state.get("items")
        if not isinstance(items, dict):
            continue

        try:
            restaurant_id = int(restaurant_key)
        except (TypeError, ValueError):
            continue

        migrated = True
        db_cart = _get_db_cart(session, restaurant_id)
        restaurant_migrated = False
        for raw_dish_id, item_state in items.items():
            try:
                dish_id = int(raw_dish_id)
            except (TypeError, ValueError):
                continue

            dish = get_public_dish(restaurant_id, dish_id)
            if not dish:
                continue

            try:
                quantity = int((item_state or {}).get("quantity") or 0)
            except (TypeError, ValueError):
                continue

            if quantity <= 0:
                continue

            note = _clean((item_state or {}).get("note"))
            if not db_cart:
                db_cart = Cart(customer_id=customer_id, restaurant_id=restaurant_id, total_amount=0)
                db.session.add(db_cart)
                db.session.flush()
            cart_item = CartItem.query.filter_by(cart_id=db_cart.cart_id, dish_id=dish.dish_id).one_or_none()

            if not cart_item:
                cart_item = CartItem(
                    cart_id=db_cart.cart_id,
                    dish_id=dish.dish_id,
                    quantity=quantity,
                    price=int(dish.price or 0),
                    note=note or None,
                )
                db.session.add(cart_item)
            else:
                cart_item.quantity = max(0, int(cart_item.quantity or 0) + quantity)
                cart_item.price = int(dish.price or 0)
                if note:
                    cart_item.note = note

            migrated = True
            restaurant_migrated = True

        if restaurant_migrated:
            db_cart.total_amount = sum(
                int(item.price or item.dish.price or 0) * max(1, int(item.quantity or 1))
                for item in db_cart.items
                if item.dish and item.quantity and int(item.quantity or 0) > 0
            )
            if not db_cart.items:
                db.session.delete(db_cart)
        restaurant_ids_to_clear.append(restaurant_key)

    if not migrated:
        return False

    for restaurant_key in restaurant_ids_to_clear:
        carts.pop(restaurant_key, None)
    session.modified = True
    db.session.commit()
    return True


def _clear_expired_successful_order_cart(session, restaurant_id):
    if not _is_logged_in_customer(session):
        return False

    customer_id = _session_user_id(session)
    if customer_id is None or restaurant_id in (None, "", 0, "0"):
        return False

    orders = (
        Order.query.filter_by(customer_id=customer_id, restaurant_id=restaurant_id)
        .order_by(Order.order_date.desc(), Order.order_id.desc())
        .all()
    )
    expired_session_keys = []
    for order in orders:
        session_key = f"success_countdown_started_at_{order.order_id}"
        started_at = session.get(session_key)
        if not started_at:
            continue

        try:
            started = datetime.fromisoformat(started_at)
        except ValueError:
            expired_session_keys.append(session_key)
            continue

        if datetime.utcnow() < started + timedelta(seconds=30):
            return False

        expired_session_keys.append(session_key)

    if not expired_session_keys:
        return False

    cleared = clear_restaurant_cart(session, restaurant_id)
    for session_key in expired_session_keys:
        session.pop(session_key, None)
    return cleared or bool(expired_session_keys)


def get_restaurant_cart_snapshot(session, restaurant_id):
    restaurant = get_public_restaurant(restaurant_id)
    if not restaurant:
        return _empty_cart_payload(restaurant_id)

    if _is_logged_in_customer(session):
        _clear_expired_successful_order_cart(session, restaurant_id)
        db_cart = _get_db_cart(session, restaurant_id)
        if db_cart:
            return _serialize_db_cart(db_cart, restaurant_id)

    cart = _ensure_restaurant_cart(session, restaurant_id)
    items_state = cart.get("items", {})
    if not items_state:
        return _empty_cart_payload(restaurant_id)

    dishes = {
        dish.dish_id: dish
        for dish in restaurant.dishes
        if dish.status
    }

    payload_items = []
    total_quantity = 0
    total_amount = 0
    dirty = False
    for raw_dish_id, item_state in list(items_state.items()):
        try:
            dish_id = int(raw_dish_id)
        except (TypeError, ValueError):
            items_state.pop(raw_dish_id, None)
            dirty = True
            continue

        dish = dishes.get(dish_id)
        if not dish:
            items_state.pop(raw_dish_id, None)
            dirty = True
            continue

        quantity = int(item_state.get("quantity") or 0)
        note = _clean(item_state.get("note"))
        if quantity <= 0:
            items_state.pop(raw_dish_id, None)
            dirty = True
            continue

        line_total = int(dish.price or 0) * quantity
        total_quantity += quantity
        total_amount += line_total
        payload_items.append(
            {
                "dish_id": dish.dish_id,
        "name": dish.dish_name or "Món ăn",
                "price": int(dish.price or 0),
                "price_text": _format_price(dish.price),
                "quantity": quantity,
                "note": note,
                "line_total": line_total,
                "line_total_text": _format_price(line_total),
                "image_path": _normalize_image_path(dish.image or _fallback_image(dish)),
            }
        )

    payload_items.sort(key=lambda item: (item["name"].lower(), item["dish_id"]))

    if dirty:
        session.modified = True
        _prune_empty_restaurant_cart(session, restaurant_id)

    return {
        "restaurant_id": restaurant_id,
        "items": payload_items,
        "total_quantity": total_quantity,
        "total_amount": total_amount,
        "total_amount_text": _format_price(total_amount),
        "is_empty": not payload_items,
    }


def add_to_restaurant_cart(session, restaurant_id, dish_id, quantity=1, note=""):
    dish = get_public_dish(restaurant_id, dish_id)
    if not dish:
        return None

    if _is_logged_in_customer(session):
        _clear_expired_successful_order_cart(session, restaurant_id)
        customer_id = _session_user_id(session)
        cart = _get_db_cart(session, restaurant_id)
        if not cart:
            cart = Cart(customer_id=customer_id, restaurant_id=restaurant_id, total_amount=0)
            db.session.add(cart)
            db.session.flush()

        cart_item = CartItem.query.filter_by(cart_id=cart.cart_id, dish_id=dish.dish_id).one_or_none()
        cleaned_note = _clean(note)
        if not cart_item:
            cart_item = CartItem(
                cart_id=cart.cart_id,
                dish_id=dish.dish_id,
                quantity=0,
                price=int(dish.price or 0),
                note=cleaned_note or None,
            )
            db.session.add(cart_item)

        current_quantity = int(cart_item.quantity or 0)
        next_quantity = max(0, current_quantity + int(quantity or 0))

        if next_quantity <= 0:
            db.session.delete(cart_item)
        else:
            cart_item.quantity = next_quantity
            cart_item.price = int(dish.price or 0)
            if cleaned_note:
                cart_item.note = cleaned_note
            elif not _clean(getattr(cart_item, "note", "")):
                cart_item.note = None

        db.session.flush()
        cart.total_amount = sum(
            int(item.price or item.dish.price or 0) * max(1, int(item.quantity or 1))
            for item in cart.items
            if item.dish and item.quantity and int(item.quantity or 0) > 0
        )
        if not cart.items:
            db.session.delete(cart)
        db.session.commit()
        return get_restaurant_cart_snapshot(session, restaurant_id)

    cart = _ensure_restaurant_cart(session, restaurant_id)
    items = cart["items"]
    item_key = str(dish_id)
    current_state = items.get(item_key, {})
    current_quantity = int(current_state.get("quantity") or 0)
    next_quantity = max(0, current_quantity + int(quantity or 0))

    if next_quantity <= 0:
        items.pop(item_key, None)
    else:
        items[item_key] = {
            "quantity": next_quantity,
            "note": _clean(note) or _clean(current_state.get("note")),
        }

    _prune_empty_restaurant_cart(session, restaurant_id)
    session.modified = True
    return get_restaurant_cart_snapshot(session, restaurant_id)


def update_restaurant_cart_item(session, restaurant_id, dish_id, quantity=None, note=None):
    dish = get_public_dish(restaurant_id, dish_id)
    if not dish:
        return None

    if _is_logged_in_customer(session):
        _clear_expired_successful_order_cart(session, restaurant_id)
        cart = _get_db_cart(session, restaurant_id)
        if not cart:
            cart = Cart(customer_id=_session_user_id(session), restaurant_id=restaurant_id, total_amount=0)
            db.session.add(cart)
            db.session.flush()

        cart_item = CartItem.query.filter_by(cart_id=cart.cart_id, dish_id=dish.dish_id).one_or_none()
        next_quantity = int(cart_item.quantity or 0) if cart_item else 0
        cleaned_note = _clean(note) if note is not None else None
        if quantity is not None:
            next_quantity = max(0, int(quantity))

        if next_quantity <= 0:
            if cart_item:
                db.session.delete(cart_item)
        else:
            if not cart_item:
                cart_item = CartItem(
                    cart_id=cart.cart_id,
                    dish_id=dish.dish_id,
                    quantity=next_quantity,
                    price=int(dish.price or 0),
                    note=cleaned_note or None,
                )
                db.session.add(cart_item)
            else:
                cart_item.quantity = next_quantity
                cart_item.price = int(dish.price or 0)
                if cleaned_note is not None:
                    cart_item.note = cleaned_note

        db.session.flush()
        if cart.items:
            cart.total_amount = sum(
                int(item.price or item.dish.price or 0) * max(1, int(item.quantity or 1))
                for item in cart.items
                if item.dish and item.quantity and int(item.quantity or 0) > 0
            )
        else:
            db.session.delete(cart)
        db.session.commit()
        return get_restaurant_cart_snapshot(session, restaurant_id)

    cart = _ensure_restaurant_cart(session, restaurant_id)
    items = cart["items"]
    item_key = str(dish_id)
    current_state = items.get(item_key, {"quantity": 0, "note": ""})
    next_quantity = int(current_state.get("quantity") or 0)
    next_note = _clean(current_state.get("note"))

    if quantity is not None:
        next_quantity = max(0, int(quantity))
    if note is not None:
        next_note = _clean(note)

    if next_quantity <= 0:
        items.pop(item_key, None)
    else:
        items[item_key] = {
            "quantity": next_quantity,
            "note": next_note,
        }

    _prune_empty_restaurant_cart(session, restaurant_id)
    session.modified = True
    return get_restaurant_cart_snapshot(session, restaurant_id)


def build_public_restaurant_context(restaurant_id, include_reviews=False, review_limit=10):
    restaurant = get_public_restaurant(restaurant_id, include_reviews=include_reviews)
    if not restaurant:
        return None

    dishes = _listed_dishes(restaurant)
    dish_views = [_dish_to_view(dish) for dish in dishes]

    categories = []
    counts = {}
    for dish_view in dish_views:
        category_name = dish_view["category"]
        if category_name not in counts:
            counts[category_name] = 0
            categories.append(category_name)
        counts[category_name] += 1

    sections = []
    for category_name in categories:
        category_slug = _slugify(category_name)
        section_items = [item for item in dish_views if item["category"] == category_name]
        sections.append(
            {
                "name": category_name,
                "slug": category_slug,
                "count": counts[category_name],
                "items": section_items,
            }
        )

    cover_image = _restaurant_cover_image(restaurant, _active_dishes(restaurant))
    review_summary = _build_public_review_summary(restaurant_id) if include_reviews else {
        "average_rating": 0,
        "review_count": 0,
        "positive_reviews": 0,
        "average_rating_text": "0.0",
        "review_count_text": "0",
        "review_count_label": "0 Đánh giá",
    }
    review_items = _build_public_review_items(restaurant_id, limit=review_limit) if include_reviews else []
    ai_review_summary_settings = get_ai_review_summary_settings()
    ai_review_summary_enabled = bool(ai_review_summary_settings["enabled"])
    ai_review_summary_available = bool(
        ai_review_summary_enabled
        and review_summary["review_count"] >= ai_review_summary_settings["min_reviews"]
    )
    return {
        "restaurant": restaurant,
        "restaurant_id": restaurant.restaurant_id,
        "restaurant_name": _restaurant_title(restaurant),
        "restaurant_address": _format_address(restaurant),
        "restaurant_description": _clean(restaurant.description) or "Thông tin nhà hàng đang được cập nhật.",
        "cover_image": cover_image,
        "categories": [
            {
                "name": section["name"],
                "slug": section["slug"],
                "count": section["count"],
            }
            for section in sections
        ],
        "menu_sections": sections,
        "dish_views": dish_views,
        "similar_restaurants": _build_similar_restaurants(restaurant),
        "review_summary": review_summary,
        "review_items": review_items,
        "review_has_more": review_summary["review_count"] > len(review_items),
        "ai_review_summary_enabled": ai_review_summary_enabled,
        "ai_review_summary_min_reviews": ai_review_summary_settings["min_reviews"],
        "ai_review_summary_available": ai_review_summary_available,
        "ai_review_summary_url": f"/restaurants/{restaurant.restaurant_id}/reviews/ai-summary",
    }
