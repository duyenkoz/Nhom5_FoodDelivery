from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Dish, Restaurant
from app.models.cart import Cart
from app.models.cart_item import CartItem
from app.services.location_service import normalize_text
from app.services.restaurant_service import build_dish_view_model, infer_image_path, infer_category


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


def _dish_name_key(dish):
    return _slugify(_clean(dish.dish_name))


def _dish_orders(dish):
    return sum(int(item.quantity or 0) for item in (dish.order_items or []))


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


def get_public_restaurant(restaurant_id):
    return (
        Restaurant.query.options(
            joinedload(Restaurant.user),
            joinedload(Restaurant.dishes).joinedload(Dish.order_items),
        )
        .filter(Restaurant.restaurant_id == restaurant_id)
        .one_or_none()
    )


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


def get_restaurant_cart_snapshot(session, restaurant_id):
    restaurant = get_public_restaurant(restaurant_id)
    if not restaurant:
        return _empty_cart_payload(restaurant_id)

    if _is_logged_in_customer(session):
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
        customer_id = _session_user_id(session)
        cart = _get_db_cart(session, restaurant_id)
        if not cart:
            cart = Cart(customer_id=customer_id, restaurant_id=restaurant_id, total_amount=0)
            db.session.add(cart)
            db.session.flush()

        cart_item = CartItem.query.filter_by(cart_id=cart.cart_id, dish_id=dish.dish_id).one_or_none()
        if not cart_item:
            cart_item = CartItem(cart_id=cart.cart_id, dish_id=dish.dish_id, quantity=0, price=int(dish.price or 0))
            db.session.add(cart_item)

        current_quantity = int(cart_item.quantity or 0)
        next_quantity = max(0, current_quantity + int(quantity or 0))

        if next_quantity <= 0:
            db.session.delete(cart_item)
        else:
            cart_item.quantity = next_quantity
            cart_item.price = int(dish.price or 0)

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
        cart = _get_db_cart(session, restaurant_id)
        if not cart:
            cart = Cart(customer_id=_session_user_id(session), restaurant_id=restaurant_id, total_amount=0)
            db.session.add(cart)
            db.session.flush()

        cart_item = CartItem.query.filter_by(cart_id=cart.cart_id, dish_id=dish.dish_id).one_or_none()
        next_quantity = int(cart_item.quantity or 0) if cart_item else 0
        if quantity is not None:
            next_quantity = max(0, int(quantity))

        if next_quantity <= 0:
            if cart_item:
                db.session.delete(cart_item)
        else:
            if not cart_item:
                cart_item = CartItem(cart_id=cart.cart_id, dish_id=dish.dish_id, quantity=next_quantity, price=int(dish.price or 0))
                db.session.add(cart_item)
            else:
                cart_item.quantity = next_quantity
                cart_item.price = int(dish.price or 0)

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


def build_public_restaurant_context(restaurant_id):
    restaurant = get_public_restaurant(restaurant_id)
    if not restaurant:
        return None

    dishes = _active_dishes(restaurant)
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

    cover_image = _restaurant_cover_image(restaurant, dishes)
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
    }
