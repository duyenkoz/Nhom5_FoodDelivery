import json
import secrets
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload
from flask import flash

from app.extensions import db
from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.payment import Payment
from app.models.review import Review
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.voucher import Voucher
from app.services.checkout_service import build_checkout_context, create_order_from_snapshot, format_payment_method_label, format_voucher_summary_label, validate_voucher_for_checkout
from app.services.notification_service import build_order_created_notification, emit_structured_notification
from app.services.auth_service import (
    complete_customer_profile,
    complete_restaurant_profile,
    create_google_customer_user,
    create_registration_user,
    ensure_customer_draft,
    is_customer_profile_complete,
    is_google_first_account,
    is_restaurant_profile_complete,
    get_restaurant_by_user_id,
    update_customer_profile,
    set_user_password,
    PHONE_PATTERN,
    USERNAME_PATTERN,
    username_exists,
    verify_password,
)
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
    _normalize_checkout_items,
    create_order_from_snapshot,
    format_order_status_label,
    validate_voucher_for_checkout,
)
from app.services.momo_service import create_momo_payment
from app.services.password_reset_service_fixed import RESEND_COOLDOWN_SECONDS
from app.services.location_service import resolve_address
from app.services.public_restaurant_service import migrate_guest_carts_to_logged_in_customer
from app.services.restaurant_service import infer_category, infer_image_path
from app.services.order_state_service import refresh_simulated_order_state
from app.utils.time_utils import format_vietnam_datetime, vietnam_now

bp = Blueprint("auth", __name__, url_prefix="/auth")
oauth_bp = Blueprint("oauth", __name__)


GOOGLE_SCOPE = "openid email profile"


def _get_google_config():
    return {
        "client_id": current_app.config.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": current_app.config.get("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": current_app.config.get("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5000/callback"),
        "auth_url": current_app.config.get("GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth"),
        "token_url": current_app.config.get("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token"),
        "userinfo_url": current_app.config.get("GOOGLE_USERINFO_URL", "https://www.googleapis.com/oauth2/v3/userinfo"),
    }


def _build_google_authorize_url(state):
    config = _get_google_config()
    query = urlencode(
        {
            "client_id": config["client_id"],
            "redirect_uri": config["redirect_uri"],
            "response_type": "code",
            "scope": GOOGLE_SCOPE,
            "state": state,
            "prompt": "select_account",
        }
    )
    return f'{config["auth_url"]}?{query}'


def _get_google_oauth_pending():
    pending = session.get("google_oauth_pending")
    return pending if isinstance(pending, dict) else {}


def _store_google_oauth_pending(state, next_url):
    pending = _get_google_oauth_pending()
    pending[state] = next_url
    if len(pending) > 5:
        for old_state in list(pending.keys())[:-5]:
            pending.pop(old_state, None)
    session["google_oauth_pending"] = pending


def _consume_google_oauth_pending(state):
    pending = _get_google_oauth_pending()
    next_url = pending.pop(state, "")
    session["google_oauth_pending"] = pending
    return next_url


def _google_urlopen_json(url, payload=None, method="GET", headers=None, timeout=10):
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    data = None
    if payload is not None:
        data = urlencode(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        try:
            return json.loads(raw)
        except Exception:
            return {"error": raw or str(exc)}
    except URLError as exc:
        return {"error": str(exc.reason) if getattr(exc, "reason", None) else str(exc)}


def _google_token_exchange(code):
    config = _get_google_config()
    return _google_urlopen_json(
        config["token_url"],
        payload={
            "code": code,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
        },
        method="POST",
    )


def _google_userinfo(access_token):
    config = _get_google_config()
    return _google_urlopen_json(
        config["userinfo_url"],
        headers={"Authorization": f"Bearer {access_token}"},
    )


def _store_google_pending_user(user, google_profile, pending_phone=False):
    session["user_id"] = user.user_id
    session["user_role"] = user.role
    session["username"] = user.username
    session["user_display_name"] = user.display_name or user.username
    session["auth_provider"] = "google"
    if pending_phone:
        session.pop("auth_state", None)
        session["google_phone_pending_user_id"] = user.user_id
        session["google_phone_pending_email"] = user.email or ""
        session["google_phone_pending_name"] = google_profile.get("name") or user.display_name or user.username
    else:
        session["auth_state"] = "logged_in"
        session.pop("google_phone_pending_user_id", None)
        session.pop("google_phone_pending_email", None)
        session.pop("google_phone_pending_name", None)
    session.permanent = False


def _clear_google_pending_session():
    session.pop("google_phone_pending_user_id", None)
    session.pop("google_phone_pending_email", None)
    session.pop("google_phone_pending_name", None)


def _google_phone_pending_context():
    pending_user_id = session.get("google_phone_pending_user_id")
    pending_user = None
    if pending_user_id:
        try:
            pending_user = db.session.get(User, int(pending_user_id))
        except (TypeError, ValueError):
            pending_user = None

    return {
        "google_phone_pending": bool(pending_user_id and pending_user),
        "google_phone_pending_name": session.get("google_phone_pending_name") or (pending_user.display_name if pending_user else ""),
        "google_phone_pending_email": session.get("google_phone_pending_email") or (pending_user.email if pending_user else ""),
    }


def _complete_google_login(user, google_profile, remember=False):
    _log_in_user_session(user, remember=remember)
    session["auth_provider"] = "google"
    session["user_display_name"] = user.display_name or google_profile.get("name") or user.username
    _clear_google_pending_session()


def _is_user_locked(user):
    return bool(user and not bool(user.status))


def _google_profile_name(profile):
    name = (profile or {}).get("name") or ""
    if name.strip():
        return name.strip()
    email = (profile or {}).get("email") or ""
    if email and "@" in email:
        return email.split("@", 1)[0]
    return ""


def _safe_next_url(next_url):
    if not next_url:
        return ""
    next_url = next_url.strip()
    if not next_url.startswith("/") or next_url.startswith("//"):
        return ""
    return next_url


def _log_in_user_session(user, remember=False):
    session["user_id"] = user.user_id
    session["user_role"] = user.role
    session["auth_state"] = "logged_in"
    session["username"] = user.username
    session["user_display_name"] = user.display_name or user.username
    session.pop("auth_provider", None)
    session.permanent = remember
    if user.role == "customer":
        migrate_guest_carts_to_logged_in_customer(session)


def _set_registration_pending_session(user):
    session["user_id"] = user.user_id
    session["user_role"] = user.role
    session["username"] = user.username
    session.pop("auth_provider", None)
    session.pop("auth_state", None)
    session.pop("user_display_name", None)
    session.permanent = False


def _is_email_or_phone(value):
    if not value:
        return False
    email_ok = "@" in value and "." in value
    phone_ok = value.startswith(("03", "05", "07", "08", "09")) and len(value) == 10 and value.isdigit()
    return email_ok or phone_ok


def _find_user_by_identifier(identifier):
    return User.query.filter(
        or_(User.email == identifier, User.phone == identifier, User.username == identifier)
    ).one_or_none()


def _is_login_identifier(value):
    return _is_email_or_phone(value) or bool(USERNAME_PATTERN.fullmatch(value))


def _mask_identifier(user):
    if not user:
        return ""

    if user.email:
        local_part, domain_part = user.email.split("@", 1)
        if len(local_part) <= 2:
            masked_local = local_part[:1] + "*"
        else:
            masked_local = local_part[:2] + "*" * max(1, len(local_part) - 2)
        return f"{masked_local}@{domain_part}"

    if user.phone:
        return f"{user.phone[:3]}****{user.phone[-3:]}"

    return ""


def _normalize_order_status(order):
    raw_status = (order.status or "").strip()
    lowered = raw_status.lower()

    if lowered in {"completed", "delivered", "done", "đã giao", "giao thành công"}:
        return {
            "bucket": "delivered",
            "label": "Đã giao",
            "badge_class": "is-success",
            "stage": "Đã giao",
            "description": "Đơn hàng đã hoàn tất và giao thành công.",
            "step_key": "delivered",
        }

    if lowered in {"đã hủy", "cancelled", "canceled"}:
        return {
            "bucket": "cancelled",
            "label": "Đã hủy",
            "badge_class": "is-muted",
            "stage": "Đã hủy",
            "description": "Đơn hàng đã bị hủy.",
            "step_key": "cancelled",
        }

    if lowered in {"refund_pending", "pending_refund", "đang chờ hoàn tiền"}:
        return {
            "bucket": "cancelled",
            "label": "Chờ hoàn tiền",
            "badge_class": "is-warning",
            "stage": "Chờ hoàn tiền",
            "description": "Đơn đã hủy sau khi thanh toán và đang chờ hoàn tiền.",
            "step_key": "refund_pending",
        }

    if lowered in {"đang giao hàng", "đang giao"}:
        return {
            "bucket": "pending",
            "label": "Đang giao hàng",
            "badge_class": "is-shipping",
            "stage": "Đang giao hàng",
            "description": "Shipper đang giao đơn đến cho bạn.",
            "step_key": "shipping",
        }

    if lowered in {"đã đến", "arrived"}:
        return {
            "bucket": "pending",
            "label": "Đã đến",
            "badge_class": "is-warning",
            "stage": "Đã đến",
            "description": "Đơn đã đến tay khách hàng.",
            "step_key": "delivered",
        }

    if lowered in {"pending_payment", "chờ thanh toán"}:
        return {
            "bucket": "pending",
            "label": "Chờ thanh toán",
            "badge_class": "is-warning",
            "stage": "Chờ thanh toán",
            "description": "Đơn sẽ tự hủy nếu không thanh toán trong 10 phút.",
            "step_key": "payment",
        }

    if lowered in {"pending", "chờ xác nhận", "đợi nhà hàng xác nhận"}:
        return {
            "bucket": "pending",
            "label": "Chờ xác nhận",
            "badge_class": "is-pending",
            "stage": "Chờ xác nhận",
            "description": "Đợi nhà hàng xác nhận đơn hàng.",
            "step_key": "confirming",
        }

    if lowered in {"đang chuẩn bị", "preparing"}:
        cancel_request_status = _clean(getattr(order, "cancel_request_status", "") or "").lower()
        if cancel_request_status == "pending":
            return {
                "bucket": "pending",
                "label": "Chờ duyệt hủy",
                "badge_class": "is-warning",
                "stage": "Chờ duyệt hủy",
                "description": "Nhà hàng đã gửi yêu cầu hủy đơn, đang chờ admin xem xét.",
                "step_key": "cancel_request",
            }
        return {
            "bucket": "pending",
            "label": "Đang chuẩn bị",
            "badge_class": "is-preparing",
            "stage": "Đang chuẩn bị",
            "description": "Nhà hàng đang chuẩn bị món.",
            "step_key": "preparing",
        }

    return {
        "bucket": "pending",
        "label": format_order_status_label(raw_status),
        "badge_class": "is-info",
        "stage": format_order_status_label(raw_status),
        "description": "Đơn đang được xử lý.",
        "step_key": "confirming",
    }


def _refresh_simulated_order_state(order):
    return refresh_simulated_order_state(order)


def _countdown_seconds(order, minutes, reference_time=None):
    reference_time = reference_time or (order.order_date if order else None)
    if not order or not reference_time:
        return 0
    remaining = int((reference_time + timedelta(minutes=minutes) - vietnam_now()).total_seconds())
    return max(0, remaining)


def _review_sentiment_from_rating(rating):
    if rating >= 4:
        return "positive"
    if rating <= 2:
        return "negative"
    return "neutral"


def _order_review_deadline(order):
    shipping_at = getattr(order, "shipping_at", None)
    if not order or not shipping_at:
        return None
    return shipping_at + timedelta(hours=24)


def _is_review_allowed_for_order(order):
    if not order:
        return False

    if (order.status or "").strip().lower() != "completed":
        return False

    if not getattr(order, "shipping_at", None):
        return False

    deadline = _order_review_deadline(order)
    return bool(deadline and vietnam_now() <= deadline)


def _build_order_review_state(order):
    review = getattr(order, "review", None) if order else None
    if order and review is None:
        review = Review.query.filter_by(order_id=order.order_id).one_or_none()

    deadline = _order_review_deadline(order)
    review_expired = bool(not deadline or vietnam_now() > deadline)

    return {
        "review": review,
        "review_exists": bool(review),
        "can_review": bool(order and not review and _is_review_allowed_for_order(order)),
        "review_expired": review_expired,
        "review_deadline": deadline,
    }


def _order_card_view(order):
    status_info = _normalize_order_status(order)
    items = order.items or []
    total_items = sum(max(1, item.quantity or 1) for item in items)
    preview_items = []
    for item in items[:2]:
        dish_name = item.dish.dish_name if item.dish else "Món ăn"
        preview_items.append(f"{max(1, item.quantity or 1)}x {dish_name}")

    return {
        "order": order,
        "order_id": order.order_id,
        "order_date": order.order_date,
        "status_info": status_info,
        "status_label": status_info["label"],
        "status_class": status_info["badge_class"],
        "status_bucket": status_info["bucket"],
        "total_amount": order.total_amount or 0,
        "delivery_address": order.delivery_address or "",
        "payment_method": order.payment.payment_method if order.payment else "cash",
        "payment_status": order.payment.status if order.payment else "",
        "restaurant_name": order.restaurant.user.display_name if order.restaurant and order.restaurant.user else "Nhà hàng",
        "restaurant_image": order.restaurant.image if order.restaurant else "",
        "item_count": total_items,
        "item_preview": preview_items,
        "detail_url": url_for("auth.order_detail", order_id=order.order_id),
        "date_text": format_vietnam_datetime(order.order_date, "%d/%m/%Y") if order.order_date else "",
        "time_text": format_vietnam_datetime(order.order_date, "%H:%M") if order.order_date else "",
    }


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = _clean(request.form.get("identifier"))
        password = request.form.get("password") or ""
        remember = request.form.get("remember") == "on"
        next_url = _safe_next_url(request.values.get("next"))
        form_values = request.form
        form_errors = {}

        if not identifier:
            form_errors["identifier"] = "Vui lòng nhập email, số điện thoại hoặc tên đăng nhập."
        elif not _is_login_identifier(identifier):
            form_errors["identifier"] = "Email, số điện thoại hoặc tên đăng nhập không hợp lệ."

        if not password:
            form_errors["password"] = "Vui lòng nhập mật khẩu."
        elif len(password) < 6:
            form_errors["password"] = "Mật khẩu tối thiểu 6 ký tự."

        if not form_errors:
            user = _find_user_by_identifier(identifier)

            if not user:
                form_errors["identifier"] = "Email, số điện thoại hoặc tên đăng nhập không đúng. Vui lòng nhập lại."
            elif _is_user_locked(user):
                form_errors["identifier"] = "Tài khoản đã bị khóa. Vui lòng liên hệ quản trị viên."
            elif not (user.password or "").strip():
                form_errors["identifier"] = "Tài khoản này đăng nhập bằng Google. Vui lòng đăng nhập bằng Google."
            elif not verify_password(user.password, password):
                form_errors["password"] = "Mật khẩu không đúng. Vui lòng nhập lại."
            else:
                _log_in_user_session(user, remember=remember)
                if user.role == "admin":
                    if next_url and next_url.startswith("/admin"):
                        return redirect(next_url)
                    return redirect(url_for("admin.dashboard"))
                if user.role == "restaurant":
                    if not is_restaurant_profile_complete(user.user_id):
                        return redirect(url_for("auth.complete_restaurant"))
                    return redirect(url_for("restaurant.dashboard"))
                if not is_customer_profile_complete(user.user_id):
                    return redirect(url_for("auth.complete_customer"))
                return redirect(url_for("home.index"))

        return render_template(
            "auth/login.html",
            form_errors=form_errors,
            form_values=form_values,
            forgot_resend_cooldown=RESEND_COOLDOWN_SECONDS,
            google_login_url=url_for("auth.google_login"),
            google_phone_submit_url=url_for("auth.google_phone_submit"),
            **_google_phone_pending_context(),
            show_search=False,
            show_auth=False,
        )

    return render_template(
        "auth/login.html",
        forgot_resend_cooldown=RESEND_COOLDOWN_SECONDS,
        google_login_url=url_for("auth.google_login"),
        google_phone_submit_url=url_for("auth.google_phone_submit"),
        **_google_phone_pending_context(),
        show_search=False,
        show_auth=False,
    )


@bp.route("/check-google-account")
def check_google_account():
    identifier = _clean(request.args.get("identifier"))
    if not identifier or not _is_login_identifier(identifier):
        return jsonify({"ok": True, "is_google_account": False, "message": ""})

    user = _find_user_by_identifier(identifier)
    is_google_account = bool(user and not (user.password or "").strip())
    return jsonify(
        {
            "ok": True,
            "is_google_account": is_google_account,
            "message": "Tài khoản này đăng nhập bằng Google. Vui lòng đăng nhập bằng Google." if is_google_account else "",
        }
    )


@bp.route("/google-login")
def google_login():
    config = _get_google_config()
    if not config["client_id"] or not config["client_secret"]:
        flash("Đăng nhập Google chưa được cấu hình.", "warning")
        return redirect(url_for("auth.login"))

    state = secrets.token_urlsafe(32)
    _store_google_oauth_pending(state, _safe_next_url(request.args.get("next")))
    return redirect(_build_google_authorize_url(state))


@bp.route("/google-phone", methods=["POST"])
def google_phone_submit():
    data = request.get_json(silent=True) or request.form or {}
    phone = _clean(data.get("phone"))
    pending_user_id = session.get("google_phone_pending_user_id")
    pending_email = (session.get("google_phone_pending_email") or "").strip().lower()

    if not pending_user_id:
        return jsonify({"ok": False, "message": "Không tìm thấy phiên Google đang chờ số điện thoại."}), 400
    if not phone:
        return jsonify({"ok": False, "message": "Vui lòng nhập số điện thoại."}), 400
    if not PHONE_PATTERN.fullmatch(phone):
        return jsonify({"ok": False, "message": "Số điện thoại phải có 10 chữ số và bắt đầu bằng 03, 05, 07, 08 hoặc 09."}), 400

    user = None
    try:
        user = db.session.get(User, int(pending_user_id))
    except (TypeError, ValueError):
        user = None

    if not user or user.role != "customer":
        _clear_google_pending_session()
        return jsonify({"ok": False, "message": "Phiên Google không hợp lệ."}), 400
    if pending_email and (user.email or "").strip().lower() != pending_email:
        _clear_google_pending_session()
        return jsonify({"ok": False, "message": "Phiên Google đã thay đổi. Vui lòng đăng nhập lại."}), 400

    other_user = User.query.filter(User.phone == phone, User.user_id != user.user_id).one_or_none()
    if other_user:
        return jsonify({"ok": False, "message": "Số điện thoại đã được sử dụng."}), 400

    user.phone = phone
    if not user.display_name:
        user.display_name = session.get("google_phone_pending_name") or user.username
    db.session.commit()

    _log_in_user_session(user)
    session["auth_provider"] = "google"
    session["user_display_name"] = user.display_name or user.username
    _clear_google_pending_session()

    return jsonify(
        {
            "ok": True,
            "redirect_url": url_for("auth.complete_customer"),
        }
    )


@oauth_bp.route("/callback")
def google_callback():
    error = request.args.get("error") or ""
    if error:
        flash("Đăng nhập Google thất bại.", "warning")
        return redirect(url_for("auth.login"))

    code = request.args.get("code") or ""
    state = request.args.get("state") or ""
    pending = _get_google_oauth_pending()

    if not code or not state or state not in pending:
        flash("Phiên đăng nhập Google không hợp lệ.", "warning")
        return redirect(url_for("auth.login"))

    next_url = _safe_next_url(_consume_google_oauth_pending(state))

    token_data = _google_token_exchange(code)
    access_token = token_data.get("access_token") or ""
    if not access_token or token_data.get("error"):
        flash("Không thể xác thực Google.", "warning")
        return redirect(url_for("auth.login"))

    profile = _google_userinfo(access_token)
    if profile.get("error"):
        flash("Không thể lấy thông tin tài khoản Google.", "warning")
        return redirect(url_for("auth.login"))

    email = _clean(profile.get("email")).lower()
    google_name = _google_profile_name(profile)
    google_sub = _clean(profile.get("sub"))
    if not email:
        flash("Google không trả về email hợp lệ.", "warning")
        return redirect(url_for("auth.login"))
    if profile.get("email_verified") is False:
        flash("Tài khoản Google chưa được xác minh email.", "warning")
        return redirect(url_for("auth.login"))

    user = User.query.filter(func.lower(User.email) == email.lower()).one_or_none()
    if user and user.role != "customer":
        flash("Chỉ tài khoản khách hàng mới có thể đăng nhập bằng Google.", "warning")
        return redirect(url_for("auth.login"))
    if _is_user_locked(user):
        flash("Tài khoản đã bị khóa. Vui lòng liên hệ quản trị viên.", "error")
        return redirect(url_for("auth.login"))

    if not user:
        try:
            user = create_google_customer_user(email, google_name, google_sub)
        except ValueError:
            flash("Không thể tạo tài khoản Google.", "warning")
            return redirect(url_for("auth.login"))

    ensure_customer_draft(user)

    if is_google_first_account(user) and not (user.phone or "").strip():
        _store_google_pending_user(user, profile, pending_phone=True)
        flash("Vui lòng nhập số điện thoại để hoàn tất tài khoản.", "info")
        return redirect(url_for("auth.login"))

    _complete_google_login(user, profile)
    if not is_customer_profile_complete(user.user_id):
        return redirect(url_for("auth.complete_customer"))

    if next_url:
        return redirect(next_url)
    return redirect(url_for("home.index"))


@bp.before_app_request
def enforce_locked_account_logout():
    if session.get("auth_state") != "logged_in":
        return None

    user_id = session.get("user_id")
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        user = None

    if user and not bool(user.status):
        session.clear()
        flash("Tài khoản đã bị khóa. Vui lòng liên hệ quản trị viên.", "error")
        return redirect(url_for("auth.login"))

    return None


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        phone = _clean(request.form.get("phone"))
        if phone and User.query.filter_by(phone=phone).first() is not None:
            return render_template(
                "auth/register.html",
                form_errors={"phone": "S\u1ed1 \u0111i\u1ec7n tho\u1ea1i \u0111\u00e3 \u0111\u01b0\u1ee3c s\u1eed d\u1ee5ng."},
                form_values=request.form,
                show_search=False,
                show_auth=False,
            )
        try:
            new_user = create_registration_user(request.form)
        except ValueError as exc:
            form_errors = exc.args[0] if exc.args else {}
            return render_template(
                "auth/register.html",
                form_errors=form_errors,
                form_values=request.form,
                show_search=False,
                show_auth=False,
            )
        _set_registration_pending_session(new_user)

        if new_user.role == "customer":
            return redirect(url_for("auth.complete_customer"))
        return redirect(url_for("auth.complete_restaurant"))

    return render_template("auth/register.html", show_search=False, show_auth=False)


@bp.route("/forgot-password/lookup", methods=["POST"])
def forgot_password_lookup():
    data = request.get_json(silent=True) or request.form
    identifier = _clean(data.get("identifier"))

    if not identifier:
        return jsonify({"ok": False, "message": "Vui lòng nhập email, số điện thoại hoặc tên đăng nhập."}), 400
    if not _is_login_identifier(identifier):
        return jsonify({"ok": False, "message": "Email, số điện thoại hoặc tên đăng nhập không hợp lệ."}), 400

    user = _find_user_by_identifier(identifier)
    if not user:
        return jsonify({"ok": False, "message": "Không tìm thấy tài khoản phù hợp."}), 404
    if is_google_first_account(user):
        return jsonify({"ok": False, "message": "Tài khoản đăng nhập bằng Google không hỗ trợ đổi mật khẩu."}), 400

    session["forgot_password_user_id"] = user.user_id

    return jsonify(
        {
            "ok": True,
            "username": user.username,
            "role": user.role,
            "masked_identifier": _mask_identifier(user),
        }
    )


@bp.route("/forgot-password/accept", methods=["POST"])
def forgot_password_accept():
    data = request.get_json(silent=True) or request.form
    identifier = _clean(data.get("identifier"))
    user_id = session.get("forgot_password_user_id")

    if not identifier or not user_id:
        return jsonify({"ok": False, "message": "Phiên xác minh đã hết hạn. Vui lòng kiểm tra lại tài khoản."}), 400

    user = _find_user_by_identifier(identifier)
    if not user or user.user_id != int(user_id):
        return jsonify({"ok": False, "message": "Tài khoản không hợp lệ."}), 400
    if is_google_first_account(user):
        return jsonify({"ok": False, "message": "Tài khoản đăng nhập bằng Google không hỗ trợ đổi mật khẩu."}), 400

    _log_in_user_session(user)
    session.pop("forgot_password_user_id", None)

    redirect_url = url_for("restaurant.dashboard") if user.role == "restaurant" else url_for("home.index")
    return jsonify(
        {
            "ok": True,
            "redirect_url": redirect_url,
        }
    )


@bp.route("/restaurant/dashboard")
def restaurant_dashboard():
    if session.get("user_role") != "restaurant":
        return redirect(url_for("home.index"))
    if not is_restaurant_profile_complete(session.get("user_id")):
        return redirect(url_for("auth.complete_restaurant"))

    return redirect(url_for("restaurant.dashboard"))


@bp.route("/account", methods=["GET", "POST"])
def account():
    if session.get("user_role") != "customer":
        return redirect(url_for("home.index"))

    user_id = session.get("user_id")
    user = (
        db.session.query(User)
        .options(selectinload(User.customer_profile))
        .filter_by(user_id=user_id)
        .one_or_none()
        if user_id
        else None
    )
    customer = user.customer_profile if user and user.customer_profile else None
    customer_address = customer.address if customer and customer.address else ""
    customer_area = customer.area if customer and customer.area else ""

    if user_id and (not customer_address or not customer_area):
        latest_order = (
            Order.query.filter_by(customer_id=user_id)
            .order_by(Order.order_date.desc())
            .first()
        )
        if latest_order and latest_order.delivery_address and not customer_address:
            customer_address = latest_order.delivery_address.strip()
        if customer_address and not customer_area:
            resolved_location = resolve_address(
                customer_address,
                selected_area=None,
                require_area_match=False,
                allow_seed_fallback=True,
            )
            if resolved_location and resolved_location.get("area"):
                customer_area = resolved_location["area"]

    form_values = {
        "tenHienThi": user.display_name if user and user.display_name else (user.username if user else ""),
        "diaChi": customer_address,
        "khuVuc": customer_area,
    }
    form_errors = {}

    if request.method == "POST":
        try:
            updated_user = update_customer_profile(session.get("user_id"), request.form)
            if updated_user:
                session["user_display_name"] = updated_user.display_name or updated_user.username
            flash("Đã cập nhật thông tin tài khoản.", "success")
            return redirect(url_for("auth.account"))
        except ValueError as exc:
            form_errors = exc.args[0] if exc.args else {}
            form_values = request.form

    return render_template(
        "auth/account.html",
        page_title="Thông tin tài khoản",
        form_values=form_values,
        form_errors=form_errors,
        customer=customer,
        user=user,
        customer_address=customer_address,
        customer_area=customer_area,
        show_search=False,
        show_auth=False,
    )


@bp.route("/orders")
def orders():
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    customer_id = session.get("user_id")
    order_rows = (
        Order.query.options(
            selectinload(Order.items).selectinload(OrderItem.dish),
            selectinload(Order.payment),
            selectinload(Order.restaurant).selectinload(Restaurant.user),
        )
        .filter_by(customer_id=customer_id)
        .order_by(Order.order_date.desc())
        .all()
    )

    for order in order_rows:
        _refresh_simulated_order_state(order)

    order_cards = [_order_card_view(order) for order in order_rows]
    pending_orders = [order for order in order_cards if order["status_bucket"] == "pending"]
    delivered_orders = [order for order in order_cards if order["status_bucket"] == "delivered"]
    cancelled_orders = [order for order in order_cards if order["status_bucket"] == "cancelled"]

    return render_template(
        "auth/orders.html",
        pending_orders=pending_orders,
        delivered_orders=delivered_orders,
        cancelled_orders=cancelled_orders,
        pending_count=len(pending_orders),
        delivered_count=len(delivered_orders),
        cancelled_count=len(cancelled_orders),
        show_search=True,
        show_auth=False,
    )


@bp.route("/orders/<int:order_id>")
def order_detail(order_id):
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    customer_id = session.get("user_id")
    order = (
        Order.query.options(
            selectinload(Order.items).selectinload(OrderItem.dish),
            selectinload(Order.payment),
            selectinload(Order.restaurant).selectinload(Restaurant.user),
            selectinload(Order.voucher),
            selectinload(Order.customer).selectinload(Customer.user),
            selectinload(Order.review),
        )
        .filter_by(order_id=order_id, customer_id=customer_id)
        .one_or_none()
    )
    if not order:
        flash("Không tìm thấy đơn hàng.", "warning")
        return redirect(url_for("auth.orders"))

    _refresh_simulated_order_state(order)
    status_info = _normalize_order_status(order)
    review_state = _build_order_review_state(order)
    payment_remaining_seconds = _countdown_seconds(order, 10) if status_info["step_key"] == "payment" else 0
    shipping_started_at = getattr(order, "shipping_at", None) or order.order_date
    shipping_remaining_seconds = _countdown_seconds(order, 1, reference_time=shipping_started_at) if status_info["step_key"] == "shipping" else 0
    customer_name = order.customer.user.display_name if order.customer and order.customer.user else ""
    customer_phone = order.customer.user.phone if order.customer and order.customer.user else ""
    try:
        item_rows_result = db.session.execute(
            text(
                """
                SELECT
                    oi.order_item_id,
                    oi.dish_id,
                    oi.quantity,
                    oi.price,
                    oi.note,
                    d.dish_name,
                    d.image,
                    d.description,
                    d.category
                FROM orderitems oi
                LEFT JOIN dishes d ON d.dish_id = oi.dish_id
                WHERE oi.order_id = :order_id
                ORDER BY oi.order_item_id ASC
                """
            ),
            {"order_id": order.order_id},
        ).mappings().all()
    except OperationalError:
        item_rows_result = db.session.execute(
            text(
                """
                SELECT
                    oi.order_item_id,
                    oi.dish_id,
                    oi.quantity,
                    oi.price,
                    d.dish_name,
                    d.image,
                    d.description,
                    d.category
                FROM orderitems oi
                LEFT JOIN dishes d ON d.dish_id = oi.dish_id
                WHERE oi.order_id = :order_id
                ORDER BY oi.order_item_id ASC
                """
            ),
            {"order_id": order.order_id},
        ).mappings().all()

    item_rows = []
    total_quantity = 0
    subtotal_amount = 0
    for item in item_rows_result:
        quantity = max(1, item.get("quantity") or 1)
        total_quantity += quantity
        line_total = (item.get("price") or 0) * quantity
        subtotal_amount += line_total
        dish_stub = SimpleNamespace(
            dish_name=item.get("dish_name") or "",
            description=item.get("description") or "",
        )
        image_path = item.get("image") or infer_image_path(item.get("category") or infer_category(dish_stub), dish_stub)
        item_rows.append(
            {
                "name": item.get("dish_name") or "Món ăn",
                "quantity": quantity,
                "price": item.get("price") or 0,
                "line_total": line_total,
                "note": item.get("note") or "",
                "image_path": image_path,
                "image_url": _image_url(image_path),
            }
        )

    applied_delivery_fee = order.delivery_fee or 0
    processing_fee_detail = 3000
    shipping_fee_detail = max(0, applied_delivery_fee - processing_fee_detail)
    voucher_discount_value = max(0, subtotal_amount + applied_delivery_fee - (order.total_amount or 0))
    payment_method_label = format_payment_method_label(order.payment.payment_method if order.payment else "")
    payment_status = (order.payment.status if order.payment else "") or ""
    payment_status_label = "Đã thanh toán" if payment_status.lower() == "paid" else (
        "Chờ thanh toán" if payment_status.lower() in {"pending", "pending_payment"} else (payment_status or "Chưa rõ")
    )
    voucher_display_text = format_voucher_summary_label(order.voucher, voucher_discount_value)
    delivery_fee_detail_text = f"Phí ship {shipping_fee_detail:,}đ · Phí xử lý đơn hàng {processing_fee_detail:,}đ"
    cancel_request_reason = (getattr(order, "cancel_request_reason", "") or "").strip()
    cancel_request_status = (getattr(order, "cancel_request_status", "") or "").strip().lower()

    return render_template(
        "auth/order_detail.html",
        order=order,
        item_rows=item_rows,
        total_quantity=total_quantity,
        status_info=status_info,
        date_text=format_vietnam_datetime(order.order_date) if order.order_date else "",
        restaurant_name=order.restaurant.user.display_name if order.restaurant and order.restaurant.user else "Nhà hàng",
        restaurant_address=order.restaurant.address if order.restaurant else "",
        customer_name=customer_name,
        customer_phone=customer_phone,
        subtotal_amount=subtotal_amount,
        voucher_discount_value=voucher_discount_value,
        voucher_display_text=voucher_display_text,
        payment_method_label=payment_method_label,
        payment_status=payment_status,
        payment_status_label=payment_status_label,
        applied_delivery_fee=applied_delivery_fee,
        delivery_fee_detail_text=delivery_fee_detail_text,
        cancel_reason=(order.cancel_reason or "").strip(),
        cancel_request_reason=cancel_request_reason,
        cancel_request_status=cancel_request_status,
        shipper_name="Shipper" if status_info["step_key"] in {"preparing", "shipping", "delivered"} else "",
        payment_remaining_seconds=payment_remaining_seconds,
        shipping_remaining_seconds=shipping_remaining_seconds,
        restaurant_image_url=_image_url(order.restaurant.image if order.restaurant else ""),
        review=review_state["review"],
        review_exists=review_state["review_exists"],
        can_review=review_state["can_review"],
        review_expired=review_state["review_expired"],
        review_deadline=review_state["review_deadline"],
        open_review_modal=request.args.get("review") == "1",
        show_search=True,
        show_auth=False,
    )


@bp.route("/orders/<int:order_id>/review", methods=["POST"])
def submit_order_review(order_id):
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    order = (
        Order.query.options(
            selectinload(Order.review),
            selectinload(Order.restaurant).selectinload(Restaurant.user),
        )
        .filter_by(order_id=order_id, customer_id=session.get("user_id"))
        .one_or_none()
    )
    if not order:
        flash("Không tìm thấy đơn hàng để đánh giá.", "warning")
        return redirect(url_for("auth.orders"))

    _refresh_simulated_order_state(order)
    review_state = _build_order_review_state(order)
    if review_state["review_exists"]:
        flash("Đơn hàng này đã được đánh giá trước đó.", "warning")
        return redirect(url_for("auth.order_detail", order_id=order.order_id))

    if not review_state["can_review"]:
        flash("Đơn hàng chỉ có thể đánh giá trong vòng 24 giờ sau khi giao thành công.", "warning")
        return redirect(url_for("auth.order_detail", order_id=order.order_id))

    rating_raw = request.form.get("rating")
    comment = (request.form.get("comment") or "").strip()
    form_errors = {}

    try:
        rating = int(rating_raw)
    except (TypeError, ValueError):
        rating = 0

    if rating < 1 or rating > 5:
        form_errors["rating"] = "Vui lòng chọn số sao từ 1 đến 5."
    if comment and len(comment) > 500:
        form_errors["comment"] = "Nội dung đánh giá không được vượt quá 500 ký tự."

    if form_errors:
        flash("Vui lòng kiểm tra lại thông tin đánh giá.", "warning")
        return redirect(url_for("auth.order_detail", order_id=order.order_id, review=1))

    existing_review = Review.query.filter_by(order_id=order.order_id).one_or_none()
    if existing_review:
        flash("Đơn hàng này đã được đánh giá trước đó.", "warning")
        return redirect(url_for("auth.order_detail", order_id=order.order_id))

    review = Review(
        customer_id=order.customer_id,
        restaurant_id=order.restaurant_id,
        order_id=order.order_id,
        rating=rating,
        comment=comment or None,
        sentiment=_review_sentiment_from_rating(rating),
        review_date=vietnam_now(),
    )
    db.session.add(review)
    db.session.commit()

    flash("Đã gửi đánh giá thành công.", "success")
    return redirect(url_for("auth.order_detail", order_id=order.order_id))


def _build_reorder_checkout_payload(order):
    items = []
    for item in order.items or []:
        dish = item.dish
        if not dish:
            continue
        quantity = max(1, _safe_int(item.quantity, 1))
        price = _safe_int(item.price if item.price is not None else getattr(dish, "price", 0), 0)
        image_path = dish.image or infer_image_path(infer_category(dish), dish)
        items.append(
            {
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
        )

    return {
        "restaurant_id": order.restaurant_id,
        "items": items,
        "delivery_fee": order.delivery_fee or 0,
        "note": "",
    }


@bp.route("/orders/<int:order_id>/reorder", methods=["POST"])
def reorder_order(order_id):
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    order = (
        Order.query.options(
            selectinload(Order.items).selectinload(OrderItem.dish),
            selectinload(Order.restaurant).selectinload(Restaurant.user),
        )
        .filter_by(order_id=order_id, customer_id=session.get("user_id"))
        .one_or_none()
    )
    if not order:
        flash("Không tìm thấy đơn hàng để đặt lại.", "warning")
        return redirect(url_for("auth.orders"))

    status_info = _normalize_order_status(order)
    if status_info["bucket"] != "delivered":
        flash("Chỉ có thể đặt lại từ đơn đã giao.", "warning")
        return redirect(url_for("auth.order_detail", order_id=order_id))

    payload = _build_reorder_checkout_payload(order)
    if not payload["restaurant_id"] or not payload["items"]:
        flash("Không đủ dữ liệu để đặt lại đơn này.", "warning")
        return redirect(url_for("auth.order_detail", order_id=order_id))

    session.pop("pending_checkout", None)
    session["checkout_payload"] = payload
    session.modified = True
    return redirect(url_for("checkout.checkout", restaurant_id=payload["restaurant_id"]))


@bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    user_id = session.get("user_id")
    restaurant_id = request.args.get("restaurant_id") or None
    form_errors = {}
    form_values = {}
    voucher_message = ""

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
                show_search=False,
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
            emit_structured_notification(
                build_order_created_notification(
                    order,
                    customer_name=snapshot.get("form_values", {}).get("customer_name", ""),
                    payment_method_label=format_payment_method_label("cash"),
                )
            )
            session.pop("pending_checkout", None)
            flash("Đặt hàng thành công.", "success")
            return redirect(url_for("auth.checkout_success", order_id=order.order_id))

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
        return_url = url_for("auth.momo_return", _external=True)
        ipn_url = url_for("auth.momo_ipn", _external=True)
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
        emit_structured_notification(
            build_order_created_notification(
                order,
                customer_name=snapshot.get("form_values", {}).get("customer_name", ""),
                payment_method_label=format_payment_method_label("momo"),
            )
        )
        pending_checkout = _build_session_checkout_payload(checkout_data, form_values=form_values, payment_method="momo")
        pending_checkout["order_id"] = order.order_id
        pending_checkout["momo_pay_url"] = momo_result.get("payUrl") if momo_result else ""
        pending_checkout["momo_order_id"] = momo_result.get("orderId") if momo_result else str(order.order_id)
        pending_checkout["momo_result_code"] = momo_result.get("resultCode") if momo_result else None
        pending_checkout["momo_message"] = momo_result.get("message") if momo_result else ""
        session["pending_checkout"] = pending_checkout
        momo_url = momo_result.get("payUrl") if momo_result else ""
        if momo_result and momo_result.get("payUrl"):
            flash("Đã tạo đơn chờ thanh toán MoMo. Vui lòng xác nhận giao dịch trong 10 phút.", "success")
        else:
            flash(momo_result.get("message") if momo_result else "Không lấy được link thanh toán MoMo, chuyển sang chế độ mô phỏng.", "warning")
        return redirect(momo_url or url_for("auth.checkout_momo"))

    checkout_data = build_checkout_context(user_id, restaurant_id=restaurant_id)
    if not checkout_data:
        flash("Không tìm thấy dữ liệu để thanh toán.", "warning")
        return redirect(url_for("home.index"))

    return render_template(
        "checkout/checkout.html",
        checkout=checkout_data,
        show_search=False,
        show_auth=False,
    )


@bp.route("/checkout/voucher", methods=["POST"])
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


@bp.route("/checkout/payload", methods=["POST"])
def checkout_payload():
    access_redirect = _require_customer_access()
    if access_redirect:
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập lại."}), 401

    data = request.get_json(silent=True) or request.form
    try:
        items = _normalize_checkout_items(data.get("items") or [])
    except (TypeError, ValueError):
        items = []

    session["checkout_payload"] = {
        "items": items,
        "delivery_fee": data.get("delivery_fee", 15000),
        "shipping_fee": data.get("shipping_fee", 0),
        "platform_fee": data.get("platform_fee", 0),
        "raw_delivery_fee": data.get("raw_delivery_fee", 0),
        "note": data.get("note", ""),
    }
    return jsonify({"ok": True, "items_count": len(items)})


@bp.route("/checkout/vouchers", methods=["GET"])
def checkout_vouchers():
    access_redirect = _require_customer_access()
    if access_redirect:
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập lại."}), 401

    restaurant_id = _clean(request.args.get("restaurant_id"))
    vouchers = _get_available_vouchers(restaurant_id)
    return jsonify({"ok": True, "vouchers": vouchers})


@bp.route("/checkout/voucher-safe", methods=["POST"])
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


@bp.route("/checkout/payload-safe", methods=["POST"])
def checkout_payload_safe():
    try:
        data = request.get_json(silent=True) or request.form
        try:
            items = _normalize_checkout_items(data.get("items") or [])
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
    except Exception:
        return jsonify({"ok": False, "message": "Không lưu được dữ liệu đơn hàng."}), 500


@bp.route("/checkout/vouchers-safe", methods=["GET"])
def checkout_vouchers_safe():
    try:
        restaurant_id = _clean(request.args.get("restaurant_id"))
        vouchers = _get_available_vouchers(restaurant_id)
        return jsonify({"ok": True, "vouchers": vouchers})
    except Exception:
        return jsonify({"ok": False, "message": "Không tải được mã khuyến mãi."}), 500


@bp.route("/checkout/momo", methods=["GET", "POST"])
def checkout_momo():
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    pending_checkout = session.get("pending_checkout") if isinstance(session.get("pending_checkout"), dict) else {}
    order_id = pending_checkout.get("order_id")
    pay_url = pending_checkout.get("momo_pay_url")

    if not order_id and request.method == "GET" and not pending_checkout:
        flash("Phiên thanh toán MoMo không hợp lệ. Vui lòng đặt hàng lại.", "warning")
        return redirect(url_for("auth.checkout"))

    order = _expire_pending_momo_order(order_id) if order_id else None
    if order and (order.status or "").lower() == "cancelled":
        session.pop("pending_checkout", None)
        flash("Đơn hàng đã quá thời gian thanh toán và đã bị hủy.", "warning")
        return redirect(url_for("auth.checkout"))

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
            return redirect(url_for("auth.checkout"))

        if not pending_checkout:
            flash("Phiên thanh toán MoMo đã hết hạn.", "warning")
            return redirect(url_for("auth.checkout"))

        if _session_payload_expired(pending_checkout):
            order = Order.query.filter_by(order_id=order_id, customer_id=session.get("user_id")).one_or_none()
            if order:
                _cancel_order_if_allowed(order)
            session.pop("pending_checkout", None)
            flash("Đơn hàng MoMo đã quá 10 phút nên đã bị hủy.", "warning")
            return redirect(url_for("auth.checkout"))

        order = Order.query.filter_by(order_id=order_id, customer_id=session.get("user_id")).one_or_none()
        if not order:
            flash("Không tìm thấy đơn hàng chờ thanh toán.", "warning")
            return redirect(url_for("auth.checkout"))

        if (order.status or "").lower() == "cancelled":
            session.pop("pending_checkout", None)
            flash("Đơn hàng đã bị hủy.", "warning")
            return redirect(url_for("auth.checkout"))

        order.status = "pending"
        if order.payment:
            order.payment.status = "paid"
        db.session.commit()
        session.pop("pending_checkout", None)
        flash("Đặt hàng thành công.", "success")
        return redirect(url_for("auth.checkout_success", order_id=order.order_id))

    if not pending_checkout:
        checkout_data = build_checkout_context(session.get("user_id"))
        if not checkout_data:
            return redirect(url_for("auth.checkout"))
        pending_checkout = _build_session_checkout_payload(checkout_data, payment_method="momo")
        if not pending_checkout.get("order_id"):
            flash("Phiên thanh toán MoMo không hợp lệ. Vui lòng đặt hàng lại.", "warning")
            return redirect(url_for("auth.checkout"))

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
        show_search=False,
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
        flash("Đặt hàng thành công.", "success")
        return redirect(url_for("auth.checkout_success", order_id=order.order_id))

    flash(message or "Thanh toán MoMo thất bại.", "error")
    return redirect(url_for("auth.checkout"))


@bp.route("/momo-ipn", methods=["POST"])
def momo_ipn():
    return jsonify({"success": True})


@bp.route("/checkout/success/<int:order_id>")
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

    return render_template(
        "checkout/success.html",
        order=order,
        subtotal_amount=subtotal_amount,
        voucher_discount_value=voucher_discount_value,
        order_status_label=format_order_status_label(order.status),
        payment_method_label=payment_method_label,
        cancel_remaining_seconds=_success_cancel_remaining(order.order_id, initialize=True),
        success_cart_clear_url=url_for("checkout.checkout_success_clear_cart", order_id=order.order_id),
        show_search=False,
        show_auth=False,
    )


@bp.route("/checkout/cancel/<int:order_id>", methods=["POST"])
def checkout_cancel(order_id):
    access_redirect = _require_customer_access()
    if access_redirect:
        return access_redirect

    order = Order.query.filter_by(order_id=order_id, customer_id=session.get("user_id")).one_or_none()
    if not order:
        flash("Không tìm thấy đơn hàng để hủy.", "warning")
        return redirect(url_for("auth.orders"))

    if (order.payment.payment_method if order.payment else "").lower() == "momo" and (order.payment.status or "").lower() == "paid":
        if _success_cancel_remaining(order.order_id, initialize=False) > 0:
            _mark_order_pending_refund(order)
            flash("Đơn hàng đang chờ hoàn tiền.", "success")
            return redirect(url_for("auth.order_detail", order_id=order.order_id))

    cancelled, message = _cancel_order_if_allowed(order)
    flash(message, "success" if cancelled else "warning")
    if (order.payment.payment_method if order.payment else "").lower() == "momo":
        return redirect(url_for("auth.order_detail", order_id=order.order_id))
    if order.restaurant_id:
        return redirect(url_for("home.restaurant_detail", restaurant_id=order.restaurant_id))
    return redirect(url_for("auth.orders"))


@bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    if session.get("auth_state") != "logged_in" or session.get("user_role") not in {"customer", "restaurant"}:
        return redirect(url_for("home.index"))

    user_id = session.get("user_id")
    user = None
    try:
        user = db.session.get(User, int(user_id)) if user_id is not None else None
    except (TypeError, ValueError):
        user = None

    if not user:
        return redirect(url_for("auth.login"))
    if is_google_first_account(user):
        flash("Tài khoản đăng nhập bằng Google không hỗ trợ đổi mật khẩu.", "warning")
        return redirect(url_for("auth.account"))

    form_errors = {}
    if request.method == "POST":
        current_password = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not current_password:
            form_errors["current_password"] = "Vui lòng nhập mật khẩu hiện tại."
        elif not verify_password(user.password, current_password):
            form_errors["current_password"] = "Mật khẩu hiện tại không đúng."

        if not new_password:
            form_errors["new_password"] = "Vui lòng nhập mật khẩu mới."
        elif len(new_password) < 6:
            form_errors["new_password"] = "Mật khẩu mới tối thiểu 6 ký tự."

        if not confirm_password:
            form_errors["confirm_password"] = "Vui lòng nhập lại mật khẩu mới."
        elif new_password and confirm_password != new_password:
            form_errors["confirm_password"] = "Mật khẩu nhập lại không khớp."

        if not form_errors:
            set_user_password(user, new_password)
            db.session.commit()
            flash("Đổi mật khẩu thành công.", "success")
            if user.role == "restaurant":
                return redirect(url_for("restaurant.dashboard"))
            return redirect(url_for("auth.account"))

    return render_template(
        "auth/change_password.html",
        form_errors=form_errors,
        form_values=request.form if request.method == "POST" else {},
        show_search=False,
        show_auth=False,
    )


@bp.route("/logout")
def logout():
    session.clear()
    response = redirect(url_for("home.index"))
    response.set_cookie("fivefood_clear_location", "1", max_age=30, httponly=True, samesite="Lax")
    return response


@bp.route("/complete-customer", methods=["GET", "POST"])
def complete_customer():
    if session.get("auth_state") == "logged_in" and session.get("user_role") == "customer" and is_customer_profile_complete(session.get("user_id")):
        return redirect(url_for("home.index"))
    if session.get("google_phone_pending_user_id") and session.get("auth_state") != "logged_in":
        flash("Vui lòng nhập số điện thoại trước khi hoàn tất hồ sơ khách hàng.", "warning")
        return redirect(url_for("auth.login"))

    user = None
    customer = None
    if session.get("user_id"):
        try:
            user = db.session.get(User, int(session.get("user_id")))
        except (TypeError, ValueError):
            user = None
        if user:
            customer = db.session.get(Customer, user.user_id)

    form_values = {
        "tenHienThi": (user.display_name if user and user.display_name else (session.get("google_phone_pending_name") if session.get("google_phone_pending_name") else (user.username if user else ""))),
        "diaChi": customer.address if customer and customer.address else "",
        "khuVuc": customer.area if customer and customer.area else "",
    }

    if request.method == "POST":
        try:
            user = complete_customer_profile(session.get("user_id"), request.form)
        except ValueError as exc:
            form_errors = exc.args[0] if exc.args else {}
            return render_template(
                "auth/complete_customer.html",
                form_errors=form_errors,
                form_values=request.form,
                show_search=False,
                show_auth=False,
            )
        if not user:
            return redirect(url_for("auth.register"))
        if session.get("auth_state") != "logged_in":
            _log_in_user_session(user)
        return redirect(url_for("home.index"))

    return render_template("auth/complete_customer.html", form_values=form_values, show_search=False, show_auth=False)


@bp.route("/complete-restaurant", methods=["GET", "POST"])
def complete_restaurant():
    is_edit_mode = request.args.get("edit") == "1" or request.args.get("edit") == "true"

    if session.get("auth_state") == "logged_in" and session.get("user_role") == "restaurant" and is_restaurant_profile_complete(session.get("user_id")) and not is_edit_mode:
        return redirect(url_for("restaurant.dashboard"))

    user_id = session.get("user_id")
    user, restaurant = get_restaurant_by_user_id(user_id)

    def _build_context(form_values=None, form_errors=None):
        values = dict(form_values or {})
        if not values:
            values = {
                "tenNhaHang": user.display_name if user and user.display_name else (user.username if user else ""),
                "diaChi": restaurant.address if restaurant and restaurant.address else "",
                "khuVuc": restaurant.area if restaurant and restaurant.area else "",
                "moTa": restaurant.description if restaurant and restaurant.description else "",
            }

        image_url = ""
        if restaurant and restaurant.image:
            image_path = restaurant.image.strip()
            if image_path.startswith(("http://", "https://", "/")):
                image_url = image_path
            elif "/" in image_path:
                image_url = url_for("static", filename=image_path)
            else:
                image_url = url_for("static", filename=f"uploads/{image_path}")

        return {
            "restaurant": restaurant,
            "restaurant_image_url": image_url,
            "form_values": values,
            "form_errors": form_errors or {},
            "is_edit_mode": is_edit_mode or bool(restaurant),
            "page_title": "Thông tin nhà hàng | Food Delivery" if (is_edit_mode or restaurant) else "Hoàn thiện thông tin nhà hàng | Food Delivery",
            "page_heading": "Thông tin nhà hàng" if (is_edit_mode or restaurant) else "Hoàn thiện thông tin nhà hàng",
            "page_subtitle": "Cập nhật lại tên, khu vực, địa chỉ hoặc ảnh nhà hàng hiện có."
            if (is_edit_mode or restaurant)
            else "Điền các thông tin cơ bản để hoàn tất hồ sơ nhà hàng.",
            "submit_label": "Lưu thay đổi" if (is_edit_mode or restaurant) else "Hoàn tất",
        }

    if request.method == "POST":
        try:
            user = complete_restaurant_profile(
                user_id,
                request.form,
                request.files.get("anhNhaHang"),
            )
        except ValueError as exc:
            form_errors = exc.args[0] if exc.args else {}
            return render_template(
                "auth/complete_restaurant.html",
                show_search=False,
                show_auth=False,
                **_build_context(form_values=request.form, form_errors=form_errors),
            )
        if not user:
            return redirect(url_for("auth.register"))
        if session.get("auth_state") == "logged_in":
            session["user_display_name"] = user.display_name or user.username
        else:
            _log_in_user_session(user)
        flash("Đã cập nhật thông tin nhà hàng." if (is_edit_mode or restaurant) else "Đã hoàn tất thông tin nhà hàng.", "success")
        return redirect(url_for("auth.complete_restaurant", edit=1)) if (is_edit_mode or restaurant) else redirect(url_for("restaurant.dashboard"))

    return render_template(
        "auth/complete_restaurant.html",
        show_search=False,
        show_auth=False,
        **_build_context(),
    )


@bp.route("/check-username")
def check_username():
    return jsonify({"exists": username_exists(request.args.get("username"))})

