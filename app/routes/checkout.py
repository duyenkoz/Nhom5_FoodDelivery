import json
from datetime import datetime, timedelta
import uuid

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from app.extensions import db
from app.models.order import Order
from app.services.checkout_service import (
    _build_checkout_form_values,
    _build_order_snapshot,
    _build_session_checkout_payload,
    _cancel_order_if_allowed,
    _clean,
    _expire_pending_momo_order,
    _get_available_vouchers,
    _image_url,
    _require_customer_access,
    _safe_int,
    _session_payload_expired,
    _success_cancel_remaining,
    build_checkout_context,
    create_order_from_snapshot,
    format_payment_method_label,
    format_order_status_label,
    format_voucher_summary_label,
    validate_voucher_for_checkout,
)
from app.services.checkout_recommendation_service import get_checkout_recommendations
from app.services.momo_service import create_momo_payment
from app.services.public_restaurant_service import clear_restaurant_cart
from app.services.restaurant_service import infer_category, infer_image_path

bp = Blueprint("checkout", __name__, url_prefix="/checkout")


def _wants_json_response():
    accept_header = request.headers.get("Accept", "")
    requested_with = request.headers.get("X-Requested-With", "")
    return "application/json" in accept_header or requested_with == "XMLHttpRequest"


def _clear_flash_messages():
    session.pop("_flashes", None)


def _checkout_redirect_url(order=None, pending_checkout=None):
    restaurant_id = None
    if order and getattr(order, "restaurant_id", None):
        restaurant_id = order.restaurant_id
    elif isinstance(pending_checkout, dict) and pending_checkout.get("restaurant_id"):
        restaurant_id = pending_checkout.get("restaurant_id")
    if restaurant_id:
        return url_for("checkout.checkout", restaurant_id=restaurant_id)
    return url_for("checkout.checkout")


def _orders_redirect_url():
    return url_for("auth.orders")


def _success_countdown_seconds(order_id, initialize=True):
    session_key = f"success_countdown_started_at_{order_id}"
    started_at = session.get(session_key)
    if not started_at:
        if not initialize:
            return 0
        started_at = datetime.utcnow().isoformat()
        session[session_key] = started_at

    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        started = datetime.utcnow()
        session[session_key] = started.isoformat()

    return max(0, int((started + timedelta(seconds=30) - datetime.utcnow()).total_seconds()))


def _mark_order_pending_refund(order):
    if not order:
        return False
    order.status = "refund_pending"
    if order.payment:
        order.payment.status = "refund_pending"
    db.session.commit()
    return True


def _build_order_item_view(item):
    dish = item.dish
    if not dish:
        return None

    quantity = max(1, _safe_int(item.quantity, 1))
    price = _safe_int(item.price if item.price is not None else getattr(dish, "price", 0), 0)
    image_path = dish.image or getattr(dish, "image", "") or ""
    if not image_path:
        image_path = infer_image_path(infer_category(dish), dish)
    return {
        "dish_id": dish.dish_id,
        "name": dish.dish_name or "Món ăn",
        "price": price,
        "quantity": quantity,
        "line_total": price * quantity,
        "image_path": image_path,
        "image_url": _image_url(image_path),
        "category": getattr(dish, "category", "") or infer_category(dish),
        "description": getattr(dish, "description", "") or "",
        "note": _clean(getattr(item, "note", "")),
    }


def _hydrate_pending_momo_checkout(order):
    if not order or not order.payment:
        return None
    if (order.payment.payment_method or "").lower() != "momo":
        return None
    if (order.status or "").lower() not in {"pending_payment", "chờ thanh toán"}:
        return None

    customer_user = order.customer.user if order.customer and order.customer.user else None
    restaurant = order.restaurant
    items = []
    subtotal = 0
    for item in order.items or []:
        item_view = _build_order_item_view(item)
        if not item_view:
            continue
        items.append(item_view)
        subtotal += item_view["line_total"]

    delivery_fee = _safe_int(order.delivery_fee, 0)
    total_amount = _safe_int(order.total_amount, subtotal + delivery_fee)
    discount_value = max(0, subtotal + delivery_fee - total_amount)
    checkout_data = {
        "customer": customer_user,
        "customer_profile": order.customer,
        "restaurant": restaurant,
        "restaurant_name": restaurant.user.display_name if restaurant and restaurant.user else "Nhà hàng",
        "items": items,
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "shipping_fee": 0,
        "platform_fee": 0,
        "raw_delivery_fee": delivery_fee,
        "distance_km": None,
        "distance_text": "",
        "shipping_rule": None,
        "discount_value": discount_value,
        "discount_text": "{:,}đ".format(discount_value) if discount_value else "0đ",
        "total_amount": total_amount,
        "voucher": order.voucher,
        "source": "resume",
    }
    form_values = {
        "customer_name": customer_user.display_name if customer_user else "",
        "phone": customer_user.phone if customer_user else "",
        "delivery_address": order.delivery_address or "",
        "note": "",
    }
    pending_checkout = _build_session_checkout_payload(checkout_data, form_values=form_values, payment_method="momo")
    pending_checkout["order_id"] = order.order_id
    pending_checkout["discount_value"] = discount_value
    pending_checkout["discount_text"] = "{:,}đ".format(discount_value) if discount_value else "0đ"
    pending_checkout["items"] = items
    pending_checkout["expires_at"] = (order.order_date + timedelta(minutes=10)).isoformat() if order.order_date else pending_checkout.get("expires_at")

    momo_order_id = f"{order.order_id}{int(datetime.utcnow().timestamp() * 1000)}{uuid.uuid4().hex[:4]}"
    momo_result = create_momo_payment(
        amount=total_amount,
        order_info=f"Thanh toán đơn hàng tại {checkout_data['restaurant_name']}",
        return_url=url_for("checkout.momo_return", _external=True),
        ipn_url=url_for("checkout.momo_ipn", _external=True),
        order_id=momo_order_id,
        extra_data={
            "order_id": order.order_id,
            "customer_id": customer_user.user_id if customer_user else None,
            "restaurant_id": restaurant.restaurant_id if restaurant else None,
            "voucher_id": order.voucher_id,
            "discount_value": discount_value,
        },
    )
    pending_checkout["momo_pay_url"] = momo_result.get("payUrl") if momo_result else ""
    pending_checkout["momo_order_id"] = momo_result.get("orderId") if momo_result else momo_order_id
    pending_checkout["momo_result_code"] = momo_result.get("resultCode") if momo_result else None
    pending_checkout["momo_message"] = momo_result.get("message") if momo_result else ""
    return pending_checkout


@bp.route("/", methods=["GET", "POST"])
def checkout():
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    user_id = session.get("user_id")
    restaurant_id = request.args.get("restaurant_id") or None
    form_errors = {}
    form_values = {}

    if request.method == "POST":
        form_values = _build_checkout_form_values(request.form)
        restaurant_id = form_values.get("restaurant_id") or restaurant_id

        checkout_data = build_checkout_context(user_id, restaurant_id=restaurant_id, form_values=form_values)
        if not checkout_data:
            flash("Không thể tải dữ liệu thanh toán.", "error")
            return redirect(url_for("home.index"))

        if not form_values.get("customer_name"):
            form_errors["customer_name"] = "Vui lòng nhập tên người nhận."
        if not form_values.get("phone"):
            form_errors["phone"] = "Vui lòng nhập số điện thoại."
        elif len(form_values.get("phone")) < 10:
            form_errors["phone"] = "Số điện thoại không hợp lệ."
        if not form_values.get("delivery_address"):
            form_errors["delivery_address"] = "Vui lòng nhập địa chỉ giao hàng."

        payment_method = form_values.get("payment_method") or "cash"
        if payment_method not in {"cash", "momo"}:
            form_errors["payment_method"] = "Vui lòng chọn phương thức thanh toán hợp lệ."

        voucher = checkout_data.get("voucher")
        discount_value = checkout_data.get("discount_value", 0) if voucher else 0
        if form_errors:
            checkout_data = build_checkout_context(
                user_id,
                restaurant_id=restaurant_id,
                form_values=form_values,
                form_errors=form_errors,
            )
            return render_template(
                "checkout/checkout.html",
                checkout=checkout_data,
                show_search=True,
                show_auth=False,
            )

        snapshot = _build_order_snapshot(checkout_data)
        if payment_method == "cash":
            order, _payment = create_order_from_snapshot(
                user_id,
                snapshot,
                "cash",
                voucher=voucher,
                discount_value=discount_value,
                order_status="pending",
                payment_status="pending",
            )
            session.pop("pending_checkout", None)
            if _wants_json_response():
                return jsonify(
                    {
                        "success": True,
                        "payment_method": "cash",
                        "order_id": order.order_id,
                        "redirect_url": url_for("checkout.checkout_success", order_id=order.order_id),
                    }
                )
            return redirect(url_for("checkout.checkout_success", order_id=order.order_id))

        order, _payment = create_order_from_snapshot(
            user_id,
            snapshot,
            "momo",
            voucher=voucher,
            discount_value=discount_value,
            order_status="pending_payment",
            payment_status="pending",
        )
        order_info = f"Thanh toán đơn hàng tại {checkout_data.get('restaurant_name') or 'Food Delivery'}"
        return_url = url_for("checkout.momo_return", _external=True)
        ipn_url = url_for("checkout.momo_ipn", _external=True)
        momo_result = create_momo_payment(
            amount=checkout_data.get("total_amount", 0),
            order_info=order_info,
            return_url=return_url,
            ipn_url=ipn_url,
            extra_data={
                "order_id": order.order_id,
                "customer_id": snapshot.get("customer_id"),
                "restaurant_id": snapshot.get("restaurant_id"),
                "voucher_id": snapshot.get("voucher_id"),
                "discount_value": snapshot.get("discount_value", 0),
            },
        )
        pending_checkout = _build_session_checkout_payload(checkout_data, form_values=form_values, payment_method="momo")
        pending_checkout["order_id"] = order.order_id
        pending_checkout["momo_pay_url"] = momo_result.get("payUrl") if momo_result else ""
        pending_checkout["momo_order_id"] = momo_result.get("orderId") if momo_result else str(order.order_id)
        pending_checkout["momo_result_code"] = momo_result.get("resultCode") if momo_result else None
        pending_checkout["momo_message"] = momo_result.get("message") if momo_result else ""
        session["pending_checkout"] = pending_checkout
        momo_url = momo_result.get("payUrl") if momo_result else ""
        redirect_url = momo_url or url_for("checkout.checkout_momo")
        if momo_result and momo_result.get("payUrl"):
            flash("Đã tạo đơn chờ thanh toán MoMo. Vui lòng xác nhận giao dịch trong 10 phút.", "success")
        else:
            flash(momo_result.get("message") if momo_result else "Không lấy được link thanh toán MoMo, chuyển sang chế độ mô phỏng.", "warning")
        if _wants_json_response():
            return jsonify(
                {
                    "success": True,
                    "payment_method": "momo",
                    "order_id": order.order_id,
                    "momo_url": momo_url or redirect_url,
                    "redirect_url": redirect_url,
                    "pay_url": momo_url,
                    "result_code": momo_result.get("resultCode") if momo_result else None,
                    "message": momo_result.get("message") if momo_result else "",
                }
            )
        return redirect(redirect_url)

    checkout_data = build_checkout_context(user_id, restaurant_id=restaurant_id)
    if not checkout_data:
        flash("Không tìm thấy dữ liệu để thanh toán.", "warning")
        return redirect(url_for("home.index"))

    return render_template(
        "checkout/checkout.html",
        checkout=checkout_data,
        show_search=True,
        show_auth=False,
    )


@bp.route("/quote", methods=["POST"])
def checkout_quote():
    access_redirect = _require_customer_access()
    if access_redirect:
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập lại."}), 401

    data = request.get_json(silent=True) or request.form
    form_values = _build_checkout_form_values(data)
    restaurant_id = form_values.get("restaurant_id") or None
    checkout_data = build_checkout_context(session.get("user_id"), restaurant_id=restaurant_id, form_values=form_values)
    if not checkout_data:
        return jsonify({"ok": False, "message": "Không thể tải dữ liệu thanh toán."}), 400

    voucher = checkout_data.get("voucher")
    return jsonify(
        {
            "ok": True,
            "voucher_id": voucher.voucher_id if voucher else "",
            "voucher_code": voucher.voucher_code if voucher else "",
            "discount_value": checkout_data.get("discount_value", 0),
            "discount_text": checkout_data.get("discount_text", "0đ"),
            "subtotal": checkout_data.get("subtotal", 0),
            "delivery_fee": checkout_data.get("delivery_fee", 0),
            "shipping_fee": checkout_data.get("shipping_fee", 0),
            "platform_fee": checkout_data.get("platform_fee", 0),
            "raw_delivery_fee": checkout_data.get("raw_delivery_fee", 0),
            "distance_km": checkout_data.get("distance_km"),
            "distance_text": checkout_data.get("distance_text", ""),
            "total_amount": checkout_data.get("total_amount", 0),
        }
    )


@bp.route("/recommendations")
def checkout_recommendations():
    access_redirect = _require_customer_access()
    if access_redirect:
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập lại."}), 401

    restaurant_id = request.args.get("restaurant_id") or None
    checkout_data = build_checkout_context(session.get("user_id"), restaurant_id=restaurant_id)
    restaurant = checkout_data.get("restaurant") if checkout_data else None
    if not checkout_data or not restaurant:
        return jsonify({"ok": False, "message": "Không thể tải gợi ý món ăn."}), 400

    cart_items = checkout_data.get("items", [])
    recommendations = get_checkout_recommendations(
        restaurant,
        cart_items,
        user_id=session.get("user_id"),
        customer_profile=checkout_data.get("customer_profile"),
        delivery_distance_km=checkout_data.get("distance_km"),
    )
    html = render_template(
        "partials/checkout_recommendations.html",
        checkout=checkout_data,
        recommendations=recommendations,
    )
    return jsonify(
        {
            "ok": True,
            "html": html,
            "recommendations": recommendations,
            "title": "Gợi ý món thêm",
            "hint": "Gợi ý theo giỏ hàng hiện tại.",
        }
    )


@bp.route("/voucher", methods=["POST"])
def checkout_voucher():
    access_redirect = _require_customer_access()
    if access_redirect:
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập lại."}), 401

    data = request.get_json(silent=True) or request.form
    voucher_code = _clean(data.get("voucher_code"))
    restaurant_id = _clean(data.get("restaurant_id"))
    form_values = {
        "voucher_code": voucher_code,
        "restaurant_id": restaurant_id,
    }
    checkout_data = build_checkout_context(session.get("user_id"), restaurant_id=restaurant_id, form_values=form_values)
    if not checkout_data:
        return jsonify({"ok": False, "message": "Không thể tải dữ liệu thanh toán."}), 400

    voucher = checkout_data.get("voucher")
    if not voucher_code:
        return jsonify(
            {
                "ok": True,
                "voucher_id": "",
                "message": "Nhập mã để kiểm tra giảm giá.",
                "discount_value": 0,
                "subtotal": checkout_data["subtotal"],
                "delivery_fee": checkout_data["delivery_fee"],
                "total_amount": checkout_data["total_amount"],
            }
        )

    if voucher:
        return jsonify(
            {
                "ok": True,
                "voucher_id": voucher.voucher_id,
                "message": "Áp dụng voucher thành công.",
                "discount_value": checkout_data["discount_value"],
                "subtotal": checkout_data["subtotal"],
                "delivery_fee": checkout_data["delivery_fee"],
                "total_amount": checkout_data["total_amount"],
            }
        )

    return jsonify(
        {
            "ok": False,
            "voucher_id": "",
            "message": checkout_data.get("voucher_error") or "Mã voucher không hợp lệ.",
            "discount_value": 0,
            "subtotal": checkout_data["subtotal"],
            "delivery_fee": checkout_data["delivery_fee"],
            "total_amount": checkout_data["total_before_discount"],
        }
    ), 400


@bp.route("/payload", methods=["POST"])
def checkout_payload():
    access_redirect = _require_customer_access()
    if access_redirect:
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập lại."}), 401

    data = request.get_json(silent=True) or request.form
    try:
        items = []
        for item in data.get("items") or []:
            items.append(item)
    except (TypeError, ValueError):
        items = []

    session["checkout_payload"] = {
        "items": items,
        "restaurant_id": _clean(data.get("restaurant_id")),
        "delivery_fee": data.get("delivery_fee", 15000),
        "shipping_fee": data.get("shipping_fee", 0),
        "platform_fee": data.get("platform_fee", 0),
        "raw_delivery_fee": data.get("raw_delivery_fee", 0),
        "note": data.get("note", ""),
    }
    return jsonify({"ok": True, "items_count": len(items)})


@bp.route("/vouchers", methods=["GET"])
def checkout_vouchers():
    access_redirect = _require_customer_access()
    if access_redirect:
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập lại."}), 401

    restaurant_id = _clean(request.args.get("restaurant_id"))
    vouchers = _get_available_vouchers(restaurant_id)
    return jsonify({"ok": True, "vouchers": vouchers})


@bp.route("/voucher-safe", methods=["POST"])
def checkout_voucher_safe():
    try:
        data = request.get_json(silent=True) or request.form
        voucher_code = _clean(data.get("voucher_code"))
        restaurant_id = _clean(data.get("restaurant_id"))
        checkout_payload = session.get("checkout_payload") if isinstance(session.get("checkout_payload"), dict) else {}
        subtotal = 0
        delivery_fee = _safe_int((checkout_payload or {}).get("delivery_fee"), 15000)
        payload_items = (checkout_payload or {}).get("items") or []
        if payload_items:
            for raw_item in payload_items:
                price = _safe_int((raw_item or {}).get("price"), 0)
                quantity = max(1, _safe_int((raw_item or {}).get("quantity"), 1))
                subtotal += price * quantity
        else:
            checkout_data = build_checkout_context(
                session.get("user_id"),
                restaurant_id=restaurant_id,
                form_values={"restaurant_id": restaurant_id},
            )
            if checkout_data:
                subtotal = checkout_data["subtotal"]
                delivery_fee = checkout_data["delivery_fee"]

        voucher, discount_value, voucher_error = validate_voucher_for_checkout(
            voucher_code,
            restaurant_id,
            subtotal,
            delivery_fee,
        )
        if voucher:
            return jsonify(
                {
                    "ok": True,
                    "voucher_id": voucher.voucher_id,
                    "message": "Áp dụng voucher thành công.",
                    "discount_value": discount_value,
                    "subtotal": subtotal,
                    "delivery_fee": delivery_fee,
                    "total_amount": max(0, subtotal + delivery_fee - discount_value),
                }
            )
        return jsonify(
            {
                "ok": False,
                "voucher_id": "",
                "message": voucher_error or "Mã voucher không hợp lệ.",
                "discount_value": 0,
                "subtotal": subtotal,
                "delivery_fee": delivery_fee,
                "total_amount": subtotal + delivery_fee,
            }
        ), 400
    except Exception:
        return jsonify({"ok": False, "message": "Không tải được voucher."}), 500


@bp.route("/payload-safe", methods=["POST"])
def checkout_payload_safe():
    try:
        data = request.get_json(silent=True) or request.form
        try:
            items = data.get("items") or []
        except (TypeError, ValueError):
            items = []

        session["checkout_payload"] = {
            "items": items,
            "delivery_fee": data.get("delivery_fee", 15000),
            "note": data.get("note", ""),
        }
        return jsonify({"ok": True, "items_count": len(items)})
    except Exception:
        return jsonify({"ok": False, "message": "Không lưu được dữ liệu đơn hàng."}), 500


@bp.route("/vouchers-safe", methods=["GET"])
def checkout_vouchers_safe():
    try:
        restaurant_id = _clean(request.args.get("restaurant_id"))
        vouchers = _get_available_vouchers(restaurant_id)
        return jsonify({"ok": True, "vouchers": vouchers})
    except Exception:
        return jsonify({"ok": False, "message": "Không tải được mã khuyến mãi."}), 500


@bp.route("/momo", methods=["GET", "POST"])
def checkout_momo():
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    pending_checkout = session.get("pending_checkout") if isinstance(session.get("pending_checkout"), dict) else {}
    requested_order_id = request.args.get("order_id", type=int)
    order_id = pending_checkout.get("order_id")
    pay_url = pending_checkout.get("momo_pay_url")

    if requested_order_id:
        order = _expire_pending_momo_order(requested_order_id)
        if not order:
            flash("Không tìm thấy đơn MoMo cần thanh toán tiếp.", "warning")
            return redirect(_orders_redirect_url())
        if (order.status or "").lower() == "cancelled":
            session.pop("pending_checkout", None)
            flash("Đơn hàng đã quá thời gian thanh toán và đã bị hủy.", "warning")
            return redirect(_orders_redirect_url())

        pending_checkout = _hydrate_pending_momo_checkout(order)
        if not pending_checkout:
            flash("Đơn hàng không còn ở trạng thái chờ thanh toán MoMo.", "warning")
            return redirect(_orders_redirect_url())

        session["pending_checkout"] = pending_checkout
        order_id = pending_checkout.get("order_id")
        pay_url = pending_checkout.get("momo_pay_url")
        if pay_url and request.method == "GET":
            return redirect(pay_url)

    if not order_id and request.method == "GET" and not pending_checkout:
        flash("Phiên thanh toán MoMo không hợp lệ. Vui lòng đặt hàng lại.", "warning")
        return redirect(_orders_redirect_url())

    order = _expire_pending_momo_order(order_id) if order_id else None
    if order and (order.status or "").lower() == "cancelled":
        session.pop("pending_checkout", None)
        flash("Đơn hàng đã quá thời gian thanh toán và đã bị hủy.", "warning")
        return redirect(_orders_redirect_url())

    remaining_seconds = 0
    if pending_checkout:
        try:
            expiry = datetime.fromisoformat(pending_checkout.get("expires_at")) if pending_checkout.get("expires_at") else None
            if expiry:
                remaining_seconds = max(0, int((expiry - datetime.utcnow()).total_seconds()))
        except ValueError:
            remaining_seconds = 0

    if request.method == "POST":
        if request.form.get("simulate_failure") == "1":
            flash("Thanh toán thất bại. Vui lòng thử lại hoặc chọn phương thức khác.", "error")
            return redirect(_orders_redirect_url())

        if not pending_checkout:
            flash("Phiên thanh toán MoMo đã hết hạn.", "warning")
            return redirect(_orders_redirect_url())

        if _session_payload_expired(pending_checkout):
            order = Order.query.filter_by(order_id=order_id, customer_id=session.get("user_id")).one_or_none()
            if order:
                _cancel_order_if_allowed(order)
            session.pop("pending_checkout", None)
            flash("Đơn hàng MoMo đã quá 10 phút nên đã bị hủy.", "warning")
            return redirect(_orders_redirect_url())

        order = Order.query.filter_by(order_id=order_id, customer_id=session.get("user_id")).one_or_none()
        if not order:
            flash("Không tìm thấy đơn hàng chờ thanh toán.", "warning")
            return redirect(_orders_redirect_url())

        if (order.status or "").lower() == "cancelled":
            session.pop("pending_checkout", None)
            flash("Đơn hàng đã bị hủy.", "warning")
            return redirect(_orders_redirect_url())

        order.status = "pending"
        if order.payment:
            order.payment.status = "paid"
        db.session.commit()
        session.pop("pending_checkout", None)
        return redirect(url_for("checkout.checkout_success", order_id=order.order_id))

    if not pending_checkout:
        checkout_data = build_checkout_context(session.get("user_id"))
        if not checkout_data:
            return redirect(_orders_redirect_url())
        pending_checkout = _build_session_checkout_payload(checkout_data, payment_method="momo")
        if not pending_checkout.get("order_id"):
            flash("Phiên thanh toán MoMo không hợp lệ. Vui lòng đặt hàng lại.", "warning")
            return redirect(_orders_redirect_url())

    if request.method == "GET" and pay_url:
        return redirect(pay_url)

    return render_template(
        "checkout/momo.html",
        checkout={
            "restaurant_name": pending_checkout.get("restaurant_name") or "",
            "subtotal": pending_checkout.get("subtotal", 0),
            "delivery_fee": pending_checkout.get("delivery_fee", 0),
            "discount_value": pending_checkout.get("discount_value", 0),
            "discount_text": "{:,}đ".format(pending_checkout.get("discount_value", 0)),
            "total_amount": pending_checkout.get("total_amount", 0),
            "items": pending_checkout.get("items", []),
            "pay_url": pay_url,
            "order_id": order_id,
            "remaining_seconds": remaining_seconds,
        },
        show_search=True,
        show_auth=False,
    )


@bp.route("/momo-return")
def momo_return():
    result_code = request.args.get("resultCode")
    order_id = request.args.get("orderId")
    extra_data_raw = request.args.get("extraData") or ""
    message = request.args.get("message") or ""
    pending_checkout = session.get("pending_checkout") if isinstance(session.get("pending_checkout"), dict) else {}
    order = None
    if pending_checkout.get("order_id"):
        order = Order.query.filter_by(order_id=pending_checkout.get("order_id"), customer_id=session.get("user_id")).one_or_none()
    if not order and extra_data_raw:
        try:
            extra_data = json.loads(extra_data_raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            extra_data = {}
        internal_order_id = extra_data.get("order_id") or extra_data.get("internal_order_id")
        if internal_order_id:
            order = Order.query.filter_by(order_id=internal_order_id, customer_id=session.get("user_id")).one_or_none()
    if not order and order_id:
        try:
            internal_order_id = int(order_id)
            order = Order.query.filter_by(order_id=internal_order_id, customer_id=session.get("user_id")).one_or_none()
        except (TypeError, ValueError):
            order = None

    if result_code == "0" and order:
        order.status = "pending"
        if order.payment:
            order.payment.status = "paid"
        db.session.commit()
        session.pop("pending_checkout", None)
        return redirect(url_for("checkout.checkout_success", order_id=order.order_id))

    _clear_flash_messages()
    flash(message or "Thanh toán MoMo thất bại.", "error")
    return redirect(_orders_redirect_url())


@bp.route("/momo-ipn", methods=["POST"])
def momo_ipn():
    return jsonify({"success": True})


@bp.route("/success/<int:order_id>")
def checkout_success(order_id):
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    order = Order.query.filter_by(order_id=order_id, customer_id=session.get("user_id")).one_or_none()
    if not order:
        flash("Không tìm thấy đơn hàng.", "warning")
        return redirect(url_for("auth.orders"))

    subtotal_amount = sum((item.price or 0) * max(1, item.quantity or 1) for item in (order.items or []))
    voucher_discount_value = max(0, subtotal_amount + (order.delivery_fee or 0) - (order.total_amount or 0))
    payment_method_label = format_payment_method_label(order.payment.payment_method if order.payment else "")
    voucher_display_text = format_voucher_summary_label(order.voucher, voucher_discount_value)
    remaining_seconds = _success_cancel_remaining(order.order_id, initialize=True)

    return render_template(
        "checkout/success.html",
        order=order,
        subtotal_amount=subtotal_amount,
        voucher_discount_value=voucher_discount_value,
        voucher_display_text=voucher_display_text,
        order_status_label=format_order_status_label(order.status),
        payment_method_label=payment_method_label,
        cancel_remaining_seconds=remaining_seconds,
        success_cart_clear_url=url_for("checkout.checkout_success_clear_cart", order_id=order.order_id),
        show_search=True,
        show_auth=False,
    )


@bp.route("/success/<int:order_id>/clear-cart", methods=["POST"])
def checkout_success_clear_cart(order_id):
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    order = Order.query.filter_by(order_id=order_id, customer_id=session.get("user_id")).one_or_none()
    if not order:
        return jsonify({"ok": False, "message": "Không tìm thấy đơn hàng."}), 404

    remaining_seconds = _success_cancel_remaining(order_id, initialize=False)
    if remaining_seconds > 0:
        return jsonify({"ok": True, "cleared": False, "remaining_seconds": remaining_seconds})

    clear_restaurant_cart(session, order.restaurant_id)
    session.pop(f"success_cart_cleared_{order_id}", None)
    return jsonify({"ok": True, "cleared": True, "remaining_seconds": 0})


@bp.route("/cancel/<int:order_id>", methods=["POST"])
def checkout_cancel(order_id):
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    order = Order.query.filter_by(order_id=order_id, customer_id=session.get("user_id")).one_or_none()
    if not order:
        flash("Không tìm thấy đơn hàng để hủy.", "warning")
        return redirect(_checkout_redirect_url())

    current_status = (order.status or "").lower()
    if current_status in {"refund_pending", "pending_refund", "đang chờ hoàn tiền"}:
        flash("Đơn hàng đang chờ hoàn tiền.", "info")
        return redirect(_orders_redirect_url())

    if (order.payment.payment_method if order.payment else "").lower() == "momo" and (order.payment.status or "").lower() == "paid":
        if _success_cancel_remaining(order.order_id, initialize=False) > 0:
            _mark_order_pending_refund(order)
            flash("Đơn hàng đang chờ hoàn tiền.", "success")
            return redirect(url_for("auth.order_detail", order_id=order.order_id))

    cancelled, message = _cancel_order_if_allowed(order)
    flash(message, "success" if cancelled else "warning")
    if cancelled and (order.payment.payment_method if order.payment else "").lower() == "momo":
        return redirect(url_for("auth.order_detail", order_id=order.order_id))
    return redirect(_checkout_redirect_url(order=order))
