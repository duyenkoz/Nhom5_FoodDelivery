from datetime import date, datetime, timedelta

from flask import redirect, session, url_for
from sqlalchemy import inspect, text

from app.extensions import db
from app.models.cart import Cart
from app.models.cart_item import CartItem
from app.models.customer import Customer
from app.models.dish import Dish
from app.models.order import Order
from app.models.payment import Payment
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.voucher import Voucher
from app.services.location_service import haversine_distance_km, resolve_address
from app.services.shipping_service import (
    get_shipping_fee_quote,
)
from app.services.restaurant_service import infer_category, infer_image_path
from app.utils.time_utils import vietnam_today

DEFAULT_DELIVERY_FEE = 15000
DEFAULT_DEMO_ITEM_COUNT = 3
_ORDERITEMS_HAS_NOTE_COLUMN = None


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _orderitems_has_note_column():
    global _ORDERITEMS_HAS_NOTE_COLUMN
    if _ORDERITEMS_HAS_NOTE_COLUMN is None:
        try:
            columns = {column["name"] for column in inspect(db.engine).get_columns("orderitems")}
            _ORDERITEMS_HAS_NOTE_COLUMN = "note" in columns
        except Exception:
            _ORDERITEMS_HAS_NOTE_COLUMN = False
    return _ORDERITEMS_HAS_NOTE_COLUMN


def _require_customer_access():
    from app.routes.auth import is_customer_profile_complete

    if session.get("auth_state") != "logged_in" or session.get("user_role") != "customer":
        return redirect(url_for("auth.login"))
    if not is_customer_profile_complete(session.get("user_id")):
        return redirect(url_for("auth.complete_customer"))
    return None


def _format_money(value):
    return "{:,}đ".format(max(0, _safe_int(value, 0)))


def _format_money_vn(value):
    return "{:,}".format(max(0, _safe_int(value, 0))).replace(",", ".")


def _user_name(user):
    if not user:
        return ""
    return (user.display_name or user.username or "").strip()


def _customer_snapshot(user_id):
    try:
        customer = db.session.get(Customer, int(user_id))
    except (TypeError, ValueError):
        customer = None

    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        user = None

    if not user:
        return None, None

    return user, customer


def _format_distance_km(distance_km):
    if distance_km is None:
        return ""
    if distance_km < 10:
        return f"{distance_km:.1f} km"
    return f"{distance_km:.0f} km"


def _resolve_distance_km(customer_profile, restaurant, delivery_address=""):
    if not customer_profile or not restaurant:
        return None

    customer_lat = None
    customer_lon = None
    restaurant_lat = restaurant.latitude
    restaurant_lon = restaurant.longitude

    if delivery_address:
        resolved = resolve_address(delivery_address, selected_area=customer_profile.area if customer_profile else None, require_area_match=False)
        if resolved:
            customer_lat = resolved.get("lat")
            customer_lon = resolved.get("lon")

    if customer_lat is None or customer_lon is None:
        customer_lat = customer_profile.latitude
        customer_lon = customer_profile.longitude

    if None not in (customer_lat, customer_lon, restaurant_lat, restaurant_lon):
        return haversine_distance_km(customer_lat, customer_lon, restaurant_lat, restaurant_lon)

    # Fallback: if the customer profile has no coordinates yet, try to reuse
    # whatever is stored on the profile and ignore the live typed address.
    return None


def _build_delivery_fee_breakdown(customer_profile, restaurant, delivery_address=""):
    distance_km = _resolve_distance_km(customer_profile, restaurant, delivery_address=delivery_address)
    shipping_quote = get_shipping_fee_quote(distance_km)
    shipping_fee = _safe_int(shipping_quote.get("fee"), 0)
    platform_fee = _safe_int(getattr(restaurant, "platform_fee", 0), 0)
    raw_delivery_fee = max(0, shipping_fee + platform_fee)
    return {
        "distance_km": distance_km,
        "distance_text": _format_distance_km(distance_km),
        "shipping_fee": shipping_fee,
        "platform_fee": platform_fee,
        "raw_delivery_fee": raw_delivery_fee,
        "delivery_fee": raw_delivery_fee,
        "shipping_rule": shipping_quote.get("rule"),
    }


def format_payment_method_label(payment_method):
    normalized = (payment_method or "").strip().lower()
    if normalized == "momo":
        return "Thanh toán qua MoMo"
    if normalized == "cash":
        return "Thanh toán bằng tiền mặt"
    return payment_method or "Thanh toán"


def format_voucher_summary_label(voucher, discount_value):
    if not voucher:
        return ""

    code = (voucher.voucher_code or "").strip()
    if not code:
        return ""

    discount_type = (voucher.discount_type or "amount").lower()
    if discount_type == "percent":
        return f"[{code}] - Giảm {max(0, _safe_int(voucher.discount_value, 0))}%"

    return f"[{code}] - Giảm {_format_money_vn(discount_value)}đ"


def format_order_status_label(status):
    normalized = (status or "").strip().lower()
    if normalized in {"completed", "delivered", "done", "đã giao", "giao thành công"}:
        return "Đã giao"
    if normalized in {"refund_pending", "pending_refund", "đang chờ hoàn tiền"}:
        return "Đang chờ hoàn tiền"
    if normalized in {"pending_payment", "chờ thanh toán"}:
        return "Chờ thanh toán"
    if normalized in {"pending", "chờ xác nhận", "đợi nhà hàng xác nhận"}:
        return "Chờ xác nhận"
    if normalized in {"preparing", "đang chuẩn bị"}:
        return "Đang chuẩn bị"
    if normalized in {"shipping", "đang giao hàng", "đang giao"}:
        return "Đang giao hàng"
    if normalized in {"cancelled", "canceled", "đã hủy"}:
        return "Đã hủy"
    return status or "Chờ xác nhận"


def _build_checkout_form_values(form):
    return {
        "customer_name": _clean(form.get("customer_name")),
        "phone": _clean(form.get("phone")),
        "delivery_address": _clean(form.get("delivery_address")),
        "note": _clean(form.get("note")),
        "payment_method": _clean(form.get("payment_method")) or "cash",
        "voucher_code": _clean(form.get("voucher_code")),
        "voucher_id": _clean(form.get("voucher_id")),
        "restaurant_id": _clean(form.get("restaurant_id")),
    }


def _resolve_restaurant(restaurant_id=None):
    if restaurant_id not in (None, "", 0, "0"):
        try:
            restaurant = db.session.get(Restaurant, int(restaurant_id))
        except (TypeError, ValueError):
            restaurant = None
        if restaurant:
            return restaurant

    return Restaurant.query.order_by(Restaurant.restaurant_id.asc()).first()


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


def _normalize_image_path(image_path):
    if not image_path:
        return ""
    image_path = image_path.strip()
    if not image_path:
        return ""
    if image_path.startswith("/static/"):
        return image_path[len("/static/") :]
    if image_path.startswith("/"):
        return image_path.lstrip("/")
    return image_path


def _resolve_dish_image_path(dish):
    image_path = _normalize_image_path(getattr(dish, "image", ""))
    if image_path:
        return image_path
    category = getattr(dish, "category", "") or infer_category(dish)
    return _normalize_image_path(infer_image_path(category, dish))


def _build_item_view(dish, quantity, price=None):
    item_price = _safe_int(price if price is not None else getattr(dish, "price", 0), 0)
    item_quantity = max(1, _safe_int(quantity, 1))
    return {
        "dish_id": dish.dish_id if dish else None,
        "name": dish.dish_name if dish else "Món ăn",
        "price": item_price,
        "quantity": item_quantity,
        "line_total": item_price * item_quantity,
        "image_path": _resolve_dish_image_path(dish) if dish else "",
        "image_url": _image_url(_resolve_dish_image_path(dish)) if dish else "",
        "category": getattr(dish, "category", "") if dish else "",
        "description": getattr(dish, "description", "") if dish else "",
        "note": "",
    }


def _build_demo_items(restaurant, limit=DEFAULT_DEMO_ITEM_COUNT):
    dishes = (
        Dish.query.filter_by(restaurant_id=restaurant.restaurant_id)
        .order_by(Dish.dish_id.asc())
        .limit(limit)
        .all()
    )
    if not dishes:
        dishes = Dish.query.order_by(Dish.dish_id.asc()).limit(limit).all()
    items = []
    for index, dish in enumerate(dishes, start=1):
        quantity = 1 if index == 1 else 2 if index == 2 else 1
        items.append(_build_item_view(dish, quantity))
    return items


def _build_cart_items(cart):
    items = []
    for cart_item in cart.items or []:
        dish = cart_item.dish
        if not dish:
            continue
        items.append(_build_item_view(dish, cart_item.quantity or 1, cart_item.price))
    return items


def _build_order_snapshot(checkout_data):
    customer = checkout_data.get("customer")
    restaurant = checkout_data.get("restaurant")
    form_values = dict(checkout_data.get("form_values") or {})

    return {
        "customer_id": customer.user_id if customer else None,
        "customer": customer,
        "restaurant_id": restaurant.restaurant_id if restaurant else None,
        "restaurant": restaurant,
        "restaurant_name": checkout_data.get("restaurant_name", ""),
        "restaurant_image_url": checkout_data.get("restaurant_image_url", ""),
        "items": checkout_data.get("items") or [],
        "subtotal": checkout_data.get("subtotal", 0),
        "delivery_fee": checkout_data.get("delivery_fee", 0),
        "shipping_fee": checkout_data.get("shipping_fee", 0),
        "platform_fee": checkout_data.get("platform_fee", 0),
        "raw_delivery_fee": checkout_data.get("raw_delivery_fee", 0),
        "distance_km": checkout_data.get("distance_km"),
        "distance_text": checkout_data.get("distance_text", ""),
        "form_values": form_values,
        "voucher_id": checkout_data.get("voucher").voucher_id if checkout_data.get("voucher") else None,
        "discount_value": checkout_data.get("discount_value", 0),
        "total_amount": checkout_data.get("total_amount", 0),
        "source": checkout_data.get("source", ""),
    }


def _build_session_checkout_payload(checkout_data, form_values=None, payment_method="cash"):
    form_values = dict(form_values or checkout_data.get("form_values") or {})
    customer = checkout_data.get("customer")
    restaurant = checkout_data.get("restaurant")
    voucher = checkout_data.get("voucher")
    return {
        "order_id": None,
        "customer_id": customer.user_id if customer else None,
        "customer_name": form_values.get("customer_name", ""),
        "phone": form_values.get("phone", ""),
        "delivery_address": form_values.get("delivery_address", ""),
        "note": form_values.get("note", ""),
        "restaurant_id": restaurant.restaurant_id if restaurant else None,
        "restaurant_name": checkout_data.get("restaurant_name", ""),
        "items": checkout_data.get("items") or [],
        "subtotal": checkout_data.get("subtotal", 0),
        "delivery_fee": checkout_data.get("delivery_fee", 0),
        "shipping_fee": checkout_data.get("shipping_fee", 0),
        "platform_fee": checkout_data.get("platform_fee", 0),
        "raw_delivery_fee": checkout_data.get("raw_delivery_fee", 0),
        "distance_km": checkout_data.get("distance_km"),
        "distance_text": checkout_data.get("distance_text", ""),
        "discount_value": checkout_data.get("discount_value", 0),
        "discount_text": checkout_data.get("discount_text", "0đ"),
        "total_amount": checkout_data.get("total_amount", 0),
        "voucher_id": voucher.voucher_id if voucher else None,
        "voucher_code": form_values.get("voucher_code", ""),
        "payment_method": payment_method,
        "item_note": "",
        "momo_pay_url": "",
        "momo_order_id": "",
        "momo_result_code": None,
        "momo_message": "",
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": (datetime.utcnow() + timedelta(minutes=10)).isoformat() if payment_method == "momo" else None,
    }


def _session_payload_expired(pending_checkout):
    if not pending_checkout:
        return False
    expires_at = pending_checkout.get("expires_at")
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    return datetime.utcnow() >= expiry


def _success_cancel_remaining(order_id, initialize=True):
    if order_id in (None, "", 0, "0"):
        return 0

    try:
        order_key = str(int(order_id))
    except (TypeError, ValueError):
        return 0

    session_key = f"success_countdown_started_at_{order_key}"
    started_at = session.get(session_key)
    if not started_at:
        if not initialize:
            return 0
        started_at = datetime.utcnow().isoformat()
        session[session_key] = started_at
        session.modified = True

    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        started = datetime.utcnow()
        session[session_key] = started.isoformat()
        session.modified = True

    remaining = int((started + timedelta(seconds=30) - datetime.utcnow()).total_seconds())
    return max(0, remaining)


def _expire_pending_momo_order(order_id):
    if not order_id:
        return None
    from app.models.order import Order

    order = Order.query.filter_by(order_id=order_id, customer_id=session.get("user_id")).one_or_none()
    if not order:
        return None
    if (order.status or "").lower() not in {"pending_payment", "chờ thanh toán"}:
        return order
    if order.order_date and datetime.utcnow() > order.order_date + timedelta(minutes=10):
        order.status = "cancelled"
        if order.payment:
            order.payment.status = "cancelled"
        db.session.commit()
    return order


def _cancel_order_if_allowed(order):
    if not order:
        return False, "Không tìm thấy đơn hàng."
    current_status = (order.status or "").lower()
    if current_status in {"refund_pending", "pending_refund", "đang chờ hoàn tiền"}:
        return False, "Đơn hàng đang chờ hoàn tiền."
    if current_status in {"cancelled", "canceled", "đã hủy"}:
        return False, "Đơn hàng đã được hủy trước đó."
    if current_status in {"pending_payment", "chờ thanh toán"}:
        order.status = "cancelled"
        if order.payment:
            order.payment.status = "cancelled"
        db.session.commit()
        return True, "Đã hủy đơn hàng chờ thanh toán."
    if current_status in {"pending", "chờ xác nhận", "đợi nhà hàng xác nhận"}:
        if _success_cancel_remaining(order.order_id, initialize=False) > 0:
            order.status = "cancelled"
            if order.payment and (order.payment.status or "").lower() != "paid":
                order.payment.status = "cancelled"
            db.session.commit()
            return True, "Đã hủy đơn hàng."
        return False, "Đã quá thời gian cho phép hủy đơn."
    return False, "Đơn hàng không thể hủy ở trạng thái hiện tại."


def _normalize_checkout_items(raw_items):
    normalized_items = []
    for raw_item in raw_items or []:
        try:
            dish_id = int(raw_item.get("dish_id"))
        except (TypeError, ValueError, AttributeError):
            dish_id = None
        if dish_id is None:
            continue

        quantity = raw_item.get("quantity", 1)
        try:
            quantity = max(1, int(quantity))
        except (TypeError, ValueError):
            quantity = 1

        price = raw_item.get("price", 0)
        try:
            price = max(0, int(price))
        except (TypeError, ValueError):
            price = 0

        image_path = _normalize_image_path(raw_item.get("image_path") or raw_item.get("image_url"))
        image_url = _image_url(_clean(raw_item.get("image_url")) or _clean(raw_item.get("image_path")))

        normalized_items.append(
            {
                "dish_id": dish_id,
                "name": _clean(raw_item.get("name")) or "Món ăn",
                "price": price,
                "quantity": quantity,
                "line_total": price * quantity,
                "image_path": image_path,
                "image_url": image_url,
                "category": _clean(raw_item.get("category")),
                "description": _clean(raw_item.get("description")),
                "note": _clean(raw_item.get("note")),
            }
        )
    return normalized_items


def _get_available_vouchers(restaurant_id=None):
    today = vietnam_today()
    restaurant_id_value = _safe_int(restaurant_id, 0)
    vouchers = Voucher.query.order_by(Voucher.voucher_id.desc()).all()
    voucher_views = []
    for voucher in vouchers:
        if not bool(voucher.status):
            continue
        if voucher.start_date and voucher.start_date > today:
            continue
        if voucher.end_date and voucher.end_date < today:
            continue
        scope = voucher.voucher_scope or "restaurant"
        if scope == "restaurant" and restaurant_id_value and voucher.created_by not in (None, restaurant_id_value):
            continue
        if scope not in {"restaurant", "system"}:
            continue
        voucher_views.append(
            {
                "voucher_id": voucher.voucher_id,
                "voucher_code": voucher.voucher_code or "",
                "discount_text": f"{voucher.discount_value or 0}%" if (voucher.discount_type or "").lower() == "percent" else f"{voucher.discount_value or 0}đ",
            }
        )
    return voucher_views


def _load_checkout_items(user_id, restaurant_id=None):
    user, customer = _customer_snapshot(user_id)
    if not user:
        return None

    restaurant = _resolve_restaurant(restaurant_id)
    if not restaurant:
        return None
    restaurant_id_value = _safe_int(restaurant.restaurant_id if restaurant else restaurant_id, 0)

    cart_query = Cart.query.filter_by(customer_id=user.user_id)
    if restaurant_id_value:
        cart_query = cart_query.filter_by(restaurant_id=restaurant_id_value)
    cart = cart_query.order_by(Cart.created_at.desc(), Cart.cart_id.desc()).first()
    if cart and cart.items:
        restaurant = cart.restaurant or restaurant
        if not restaurant and cart.items[0].dish and cart.items[0].dish.restaurant:
            restaurant = cart.items[0].dish.restaurant
        items = _build_cart_items(cart)
        subtotal = sum(item["line_total"] for item in items)
        fee_breakdown = _build_delivery_fee_breakdown(customer, restaurant, delivery_address="")
        return {
            "customer": user,
            "customer_profile": customer,
            "restaurant": restaurant,
            "items": items,
            "subtotal": subtotal,
            "delivery_fee": fee_breakdown["delivery_fee"],
            "shipping_fee": fee_breakdown["shipping_fee"],
            "platform_fee": fee_breakdown["platform_fee"],
            "raw_delivery_fee": fee_breakdown["raw_delivery_fee"],
            "distance_km": fee_breakdown["distance_km"],
            "distance_text": fee_breakdown["distance_text"],
            "shipping_rule": fee_breakdown["shipping_rule"],
            "note": "",
            "source": "cart",
        }

    checkout_payload = session.get("checkout_payload")
    payload_restaurant_id = _safe_int((checkout_payload or {}).get("restaurant_id"), 0) if isinstance(checkout_payload, dict) else 0
    if isinstance(checkout_payload, dict) and checkout_payload.get("items") and payload_restaurant_id and (
        not restaurant_id_value or payload_restaurant_id == restaurant_id_value
    ):
        payload_items = []
        for raw_item in checkout_payload.get("items", []):
            payload_items.append(
                {
                    "dish_id": raw_item.get("dish_id"),
                    "name": raw_item.get("name") or "Món ăn",
                    "price": _safe_int(raw_item.get("price"), 0),
                    "quantity": max(1, _safe_int(raw_item.get("quantity"), 1)),
                    "line_total": _safe_int(raw_item.get("price"), 0) * max(1, _safe_int(raw_item.get("quantity"), 1)),
                    "image_url": _image_url(raw_item.get("image_url")),
                    "category": raw_item.get("category", ""),
                    "description": raw_item.get("description", ""),
                    "note": _clean(raw_item.get("note")),
                }
            )

        subtotal = sum(item["line_total"] for item in payload_items)
        delivery_fee = _safe_int(checkout_payload.get("delivery_fee"), DEFAULT_DELIVERY_FEE)
        return {
            "customer": user,
            "customer_profile": customer,
            "restaurant": restaurant,
            "items": payload_items,
            "subtotal": subtotal,
            "delivery_fee": delivery_fee,
            "note": checkout_payload.get("note", ""),
            "source": "session",
        }

    cart_query = Cart.query.filter_by(customer_id=user.user_id)
    if restaurant_id_value:
        cart_query = cart_query.filter_by(restaurant_id=restaurant_id_value)
    cart = cart_query.order_by(Cart.created_at.desc(), Cart.cart_id.desc()).first()
    if cart and cart.items:
        restaurant = cart.restaurant or restaurant
        if not restaurant and cart.items[0].dish and cart.items[0].dish.restaurant:
            restaurant = cart.items[0].dish.restaurant
        items = _build_cart_items(cart)
        subtotal = sum(item["line_total"] for item in items)
        return {
            "customer": user,
            "customer_profile": customer,
            "restaurant": restaurant,
            "items": items,
            "subtotal": subtotal,
            "delivery_fee": DEFAULT_DELIVERY_FEE,
            "note": "",
            "source": "cart",
        }

    items = _build_demo_items(restaurant)
    subtotal = sum(item["line_total"] for item in items)
    return {
        "customer": user,
        "customer_profile": customer,
        "restaurant": restaurant,
        "items": items,
        "subtotal": subtotal,
        "delivery_fee": DEFAULT_DELIVERY_FEE,
        "note": "",
        "source": "demo",
    }


def _load_checkout_items_v2(user_id, restaurant_id=None):
    user, customer = _customer_snapshot(user_id)
    if not user:
        return None

    restaurant = _resolve_restaurant(restaurant_id)
    if not restaurant:
        return None
    restaurant_id_value = _safe_int(restaurant.restaurant_id if restaurant else restaurant_id, 0)

    checkout_payload = session.get("checkout_payload")
    payload_restaurant_id = _safe_int((checkout_payload or {}).get("restaurant_id"), 0) if isinstance(checkout_payload, dict) else 0
    if isinstance(checkout_payload, dict) and checkout_payload.get("items") and payload_restaurant_id and (
        not restaurant_id_value or payload_restaurant_id == restaurant_id_value
    ):
        payload_items = []
        for raw_item in checkout_payload.get("items", []):
            price = _safe_int(raw_item.get("price"), 0)
            quantity = max(1, _safe_int(raw_item.get("quantity"), 1))
            image_path = _normalize_image_path(raw_item.get("image_path") or raw_item.get("image_url"))
            payload_items.append(
                {
                    "dish_id": raw_item.get("dish_id"),
                    "name": raw_item.get("name") or "Món ăn",
                    "price": price,
                    "quantity": quantity,
                    "line_total": price * quantity,
                    "image_path": image_path,
                    "image_url": _image_url(raw_item.get("image_url") or image_path),
                    "category": raw_item.get("category", ""),
                    "description": raw_item.get("description", ""),
                    "note": _clean(raw_item.get("note")),
                }
            )

        subtotal = sum(item["line_total"] for item in payload_items)
        platform_fee = _safe_int(getattr(restaurant, "platform_fee", 0), 0)
        shipping_fee = _safe_int(
            checkout_payload.get("shipping_fee"),
            max(0, _safe_int(checkout_payload.get("delivery_fee"), DEFAULT_DELIVERY_FEE) - platform_fee),
        )
        raw_delivery_fee = max(
            0,
            _safe_int(checkout_payload.get("raw_delivery_fee"), shipping_fee + platform_fee),
        )
        return {
            "customer": user,
            "customer_profile": customer,
            "restaurant": restaurant,
            "items": payload_items,
            "subtotal": subtotal,
            "delivery_fee": raw_delivery_fee,
            "shipping_fee": shipping_fee,
            "platform_fee": platform_fee,
            "raw_delivery_fee": raw_delivery_fee,
            "distance_km": checkout_payload.get("distance_km"),
            "distance_text": checkout_payload.get("distance_text", ""),
            "note": checkout_payload.get("note", ""),
            "source": "session",
        }

    cart_query = Cart.query.filter_by(customer_id=user.user_id)
    if restaurant_id_value:
        cart_query = cart_query.filter_by(restaurant_id=restaurant_id_value)
    cart = cart_query.order_by(Cart.created_at.desc(), Cart.cart_id.desc()).first()
    if cart and cart.items:
        restaurant = cart.restaurant or restaurant
        if not restaurant and cart.items[0].dish and cart.items[0].dish.restaurant:
            restaurant = cart.items[0].dish.restaurant
        items = _build_cart_items(cart)
        subtotal = sum(item["line_total"] for item in items)
        fee_breakdown = _build_delivery_fee_breakdown(customer, restaurant, delivery_address="")
        return {
            "customer": user,
            "customer_profile": customer,
            "restaurant": restaurant,
            "items": items,
            "subtotal": subtotal,
            "delivery_fee": fee_breakdown["delivery_fee"],
            "shipping_fee": fee_breakdown["shipping_fee"],
            "platform_fee": fee_breakdown["platform_fee"],
            "raw_delivery_fee": fee_breakdown["raw_delivery_fee"],
            "distance_km": fee_breakdown["distance_km"],
            "distance_text": fee_breakdown["distance_text"],
            "shipping_rule": fee_breakdown["shipping_rule"],
            "note": "",
            "source": "cart",
        }

    items = _build_demo_items(restaurant)
    subtotal = sum(item["line_total"] for item in items)
    fee_breakdown = _build_delivery_fee_breakdown(customer, restaurant, delivery_address="")
    return {
        "customer": user,
        "customer_profile": customer,
        "restaurant": restaurant,
        "items": items,
        "subtotal": subtotal,
        "delivery_fee": fee_breakdown["delivery_fee"],
        "shipping_fee": fee_breakdown["shipping_fee"],
        "platform_fee": fee_breakdown["platform_fee"],
        "raw_delivery_fee": fee_breakdown["raw_delivery_fee"],
        "distance_km": fee_breakdown["distance_km"],
        "distance_text": fee_breakdown["distance_text"],
        "shipping_rule": fee_breakdown["shipping_rule"],
        "note": "",
        "source": "demo",
    }


def _voucher_discount_value(voucher, subtotal, delivery_fee):
    base_amount = max(0, _safe_int(subtotal, 0) + _safe_int(delivery_fee, 0))
    if not voucher:
        return 0

    discount_type = (voucher.discount_type or "amount").lower()
    discount_value = _safe_int(voucher.discount_value, 0)

    if discount_type == "percent":
        return min(base_amount, base_amount * max(0, discount_value) // 100)
    return min(base_amount, max(0, discount_value))


def validate_voucher_for_checkout(voucher_code, restaurant_id, subtotal, delivery_fee):
    code = _clean(voucher_code).upper()
    if not code:
        return None, 0, ""

    voucher = Voucher.query.filter(db.func.upper(Voucher.voucher_code) == code).one_or_none()
    if not voucher:
        return None, 0, "Mã voucher không hợp lệ."

    today = vietnam_today()
    if not bool(voucher.status):
        return None, 0, "Voucher hiện đang tắt."
    if voucher.start_date and voucher.start_date > today:
        return None, 0, "Voucher chưa đến ngày áp dụng."
    if voucher.end_date and voucher.end_date < today:
        return None, 0, "Voucher đã hết hạn."

    scope = voucher.voucher_scope or "restaurant"
    if scope == "restaurant" and voucher.created_by not in (None, _safe_int(restaurant_id, 0)):
        return None, 0, "Voucher này không áp dụng cho nhà hàng đang thanh toán."

    discount_value = _voucher_discount_value(voucher, subtotal, delivery_fee)
    return voucher, discount_value, ""


def build_checkout_context(user_id, restaurant_id=None, form_values=None, form_errors=None, voucher_message=""):
    form_values = dict(form_values or {})
    restaurant_hint = restaurant_id or form_values.get("restaurant_id")
    checkout_data = _load_checkout_items_v2(user_id, restaurant_hint)
    if not checkout_data:
        return None

    customer = checkout_data["customer"]
    customer_profile = checkout_data["customer_profile"]
    restaurant = checkout_data["restaurant"]
    items = checkout_data["items"]
    subtotal = checkout_data["subtotal"]
    delivery_fee = checkout_data["delivery_fee"]
    total_before_discount = subtotal + delivery_fee

    if not form_values:
        form_values = {
            "customer_name": _user_name(customer),
            "phone": customer.phone if customer else "",
            "delivery_address": customer_profile.address if customer_profile and customer_profile.address else "",
            "note": "",
            "payment_method": "cash",
            "voucher_code": "",
            "voucher_id": "",
            "restaurant_id": restaurant.restaurant_id if restaurant else "",
        }
    elif not form_values.get("delivery_address") and customer_profile and customer_profile.address:
        form_values["delivery_address"] = customer_profile.address

    fee_breakdown = _build_delivery_fee_breakdown(
        customer_profile,
        restaurant,
        delivery_address=form_values.get("delivery_address", ""),
    )
    delivery_fee = fee_breakdown["delivery_fee"]
    checkout_data["delivery_fee"] = delivery_fee
    checkout_data["shipping_fee"] = fee_breakdown["shipping_fee"]
    checkout_data["platform_fee"] = fee_breakdown["platform_fee"]
    checkout_data["raw_delivery_fee"] = fee_breakdown["raw_delivery_fee"]
    checkout_data["distance_km"] = fee_breakdown["distance_km"]
    checkout_data["distance_text"] = fee_breakdown["distance_text"]
    checkout_data["shipping_rule"] = fee_breakdown["shipping_rule"]
    total_before_discount = subtotal + delivery_fee

    voucher_code = _clean(form_values.get("voucher_code"))
    voucher = None
    discount_value = 0
    voucher_error = voucher_message or ""
    if voucher_code:
        voucher, discount_value, voucher_error = validate_voucher_for_checkout(
            voucher_code,
            restaurant.restaurant_id if restaurant else None,
            subtotal,
            delivery_fee,
        )
        if voucher:
            form_values["voucher_id"] = voucher.voucher_id
        else:
            form_values["voucher_id"] = ""

    total_amount = max(0, total_before_discount - discount_value)
    restaurant_name = _user_name(restaurant.user) if restaurant and restaurant.user else "Nhà hàng"

    return {
        "customer": customer,
        "customer_profile": customer_profile,
        "restaurant": restaurant,
        "restaurant_name": restaurant_name,
        "restaurant_image_url": _image_url(getattr(restaurant, "image", "")) if restaurant else "",
        "items": items,
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "shipping_fee": checkout_data.get("shipping_fee", 0),
        "platform_fee": checkout_data.get("platform_fee", 0),
        "raw_delivery_fee": checkout_data.get("raw_delivery_fee", 0),
        "distance_km": checkout_data.get("distance_km"),
        "distance_text": checkout_data.get("distance_text", ""),
        "shipping_rule": checkout_data.get("shipping_rule"),
        "total_before_discount": total_before_discount,
        "discount_value": discount_value,
        "discount_text": _format_money(discount_value) if discount_value else "0đ",
        "voucher_summary_label": format_voucher_summary_label(voucher, discount_value),
        "total_amount": total_amount,
        "voucher": voucher,
        "voucher_error": voucher_error,
        "form_values": form_values,
        "form_errors": form_errors or {},
        "source": checkout_data["source"],
    }


def create_order_from_snapshot(
    user_id,
    snapshot,
    payment_method,
    voucher=None,
    discount_value=0,
    order_status=None,
    payment_status=None,
):
    customer = snapshot["customer"]
    restaurant = snapshot["restaurant"]
    items = snapshot["items"]
    delivery_address = _clean(snapshot["form_values"].get("delivery_address"))
    note = _clean(snapshot["form_values"].get("note"))
    subtotal = snapshot["subtotal"]
    delivery_fee = snapshot["delivery_fee"]
    total_amount = max(0, subtotal + delivery_fee - _safe_int(discount_value, 0))
    resolved_order_status = order_status or ("pending" if payment_method in {"cash", "momo"} else "pending")
    resolved_payment_status = payment_status or ("paid" if payment_method == "momo" else "pending")

    order = Order(
        customer_id=customer.user_id,
        voucher_id=voucher.voucher_id if voucher else None,
        order_date=datetime.utcnow(),
        total_amount=total_amount,
        delivery_fee=delivery_fee,
        delivery_address=delivery_address,
        status=resolved_order_status,
        restaurant_id=restaurant.restaurant_id if restaurant else None,
    )
    db.session.add(order)
    db.session.flush()

    for item in items:
        insert_params = {
            "order_id": order.order_id,
            "dish_id": item.get("dish_id"),
            "quantity": item.get("quantity") or 1,
            "price": item.get("price") or 0,
            "note": _clean(item.get("note")),
        }
        if _orderitems_has_note_column():
            db.session.execute(
                text(
                    """
                    INSERT INTO orderitems (order_id, dish_id, quantity, price, note)
                    VALUES (:order_id, :dish_id, :quantity, :price, :note)
                    """
                ),
                insert_params,
            )
        else:
            db.session.execute(
                text(
                    """
                    INSERT INTO orderitems (order_id, dish_id, quantity, price)
                    VALUES (:order_id, :dish_id, :quantity, :price)
                    """
                ),
                insert_params,
            )

    payment = Payment(
        order_id=order.order_id,
        payment_method=payment_method,
        status=resolved_payment_status,
        payment_date=datetime.utcnow(),
    )
    db.session.add(payment)
    db.session.commit()

    return order, payment
