from datetime import date
from datetime import timedelta
import calendar
import re

from sqlalchemy import or_
from sqlalchemy import cast, String
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.customer import Customer
from app.models.order import Order
from app.models.review import Review
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.voucher import Voucher
from app.services.shipping_service import build_shipping_rules_form_values, get_shipping_fee_settings
from app.services.restaurant_service import EXCLUDED_ORDER_STATUSES
from app.services.system_setting_service import get_setting
from app.utils.time_utils import format_vietnam_date, format_vietnam_datetime


ROLE_OPTIONS = ("all", "customer", "restaurant", "admin")
ROLE_LABELS = {
    "all": 'Tất cả',
    "customer": 'Khách hàng',
    "restaurant": 'Nhà hàng',
    "admin": 'Quản trị viên',
}

ADMIN_PROCESSING_FEE = 3000


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


SECTION_PAGE_SIZES = {
    "accounts": 8,
    "vouchers": 9,
    "reviews": 5,
    "review_reports": 5,
    "complaints": 5,
    "disputes": 8,
    "shipping_fees": 6,
    "reports": 12,
    "search_settings": 1,
}


def _safe_name(user):
    if not user:
        return 'Chưa rõ'
    return (user.display_name or user.username or 'Chưa rõ').strip()


def _safe_role(role):
    return role if role in {"admin", "customer", "restaurant"} else "customer"


def _normalize_role_filter(value):
    value = _clean(value) or "all"
    return value if value in ROLE_OPTIONS else "all"


def _match_query(*values, query=""):
    query_slug = _clean(query).lower()
    if not query_slug:
        return True
    haystack = " ".join(str(value or "") for value in values).lower()
    return query_slug in haystack


def _format_datetime(value):
    return format_vietnam_datetime(value) if value else ""


def _format_date(value):
    return format_vietnam_date(value) if value else ""


def _format_money(value):
    return '{:,}đ'.format(max(0, int(value or 0)))


def _format_money_signed(value):
    return '{:,}đ'.format(int(value or 0))


def _order_bucket(status):
    normalized = _clean(status).lower()
    if normalized in {"pending", "pending_payment"}:
        return "pending"
    if normalized == "preparing":
        return "preparing"
    if normalized in {"ready_for_delivery", "waiting_delivery", "shipping"}:
        return "shipping"
    if normalized in {"completed", "delivered", "done"}:
        return "completed"
    if normalized in EXCLUDED_ORDER_STATUSES or normalized in {"cancelled", "canceled"}:
        return "cancelled"
    return "other"


def _build_revenue_summary(source_orders):
    summary = {
        "completed_orders": 0,
        "processing_fee_total": 0,
        "restaurant_platform_fee_total": 0,
        "system_voucher_discount_total": 0,
        "merchant_voucher_discount_total": 0,
        "gross_platform_income_total": 0,
        "net_admin_revenue_total": 0,
        "voucher_discount_total": 0,
    }
    for order in source_orders:
        breakdown = _order_admin_revenue_breakdown(order)
        summary["completed_orders"] += 1
        summary["processing_fee_total"] += breakdown["processing_fee"]
        summary["restaurant_platform_fee_total"] += breakdown["restaurant_platform_fee"]
        summary["system_voucher_discount_total"] += breakdown["system_voucher_discount"]
        summary["merchant_voucher_discount_total"] += breakdown["merchant_voucher_discount"]
        summary["gross_platform_income_total"] += breakdown["platform_income"]
        summary["net_admin_revenue_total"] += breakdown["net_admin_revenue"]
        summary["voucher_discount_total"] += breakdown["discount_amount"]
    return summary


def _safe_percentage(numerator, denominator):
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _order_admin_revenue_breakdown(order):
    items = order.items or []
    subtotal_amount = sum(_clean_int(item.price) * max(1, _clean_int(item.quantity, 1)) for item in items)
    delivery_fee_amount = max(0, _clean_int(getattr(order, "delivery_fee", 0)))
    total_amount = max(0, _clean_int(getattr(order, "total_amount", 0)))
    restaurant_platform_fee = max(0, _clean_int(getattr(getattr(order, "restaurant", None), "platform_fee", 0)))
    discount_amount = max(0, subtotal_amount + delivery_fee_amount - total_amount)

    voucher = getattr(order, "voucher", None)
    voucher_scope = _clean(getattr(voucher, "voucher_scope", "")).lower() if voucher else ""
    system_voucher_discount = discount_amount if voucher and voucher_scope == "system" else 0
    merchant_voucher_discount = discount_amount if voucher and voucher_scope == "restaurant" else 0
    processing_fee = ADMIN_PROCESSING_FEE
    platform_income = processing_fee + restaurant_platform_fee
    net_admin_revenue = platform_income - system_voucher_discount

    return {
        "subtotal_amount": subtotal_amount,
        "delivery_fee_amount": delivery_fee_amount,
        "total_amount": total_amount,
        "processing_fee": processing_fee,
        "restaurant_platform_fee": restaurant_platform_fee,
        "platform_income": platform_income,
        "discount_amount": discount_amount,
        "system_voucher_discount": system_voucher_discount,
        "merchant_voucher_discount": merchant_voucher_discount,
        "net_admin_revenue": net_admin_revenue,
    }


def _clean_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_iso_date(value):
    value = _clean(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _analytics_period_reference(period, date_value="", month_value="", year_value=""):
    today = date.today()
    normalized_period = (_clean(period) or "month").lower()

    if normalized_period == "day":
        anchor = _parse_iso_date(date_value) or today
        return normalized_period, anchor

    if normalized_period == "year":
        try:
            return normalized_period, int(_clean(year_value) or today.year)
        except (TypeError, ValueError):
            return normalized_period, today.year

    try:
        if _clean(month_value):
            year_text, month_text = _clean(month_value).split("-", 1)
            reference_year = int(year_text)
            reference_month = int(month_text)
        else:
            reference_year = today.year
            reference_month = today.month
        if reference_month < 1 or reference_month > 12:
            raise ValueError
    except (TypeError, ValueError):
        reference_year = today.year
        reference_month = today.month

    return "month", (reference_year, reference_month)


def _analytics_window_bounds(period, anchor):
    normalized = (_clean(period) or "month").lower()
    if normalized == "day":
        start_date = anchor
        end_date = anchor
    elif normalized == "year":
        start_date = date(anchor, 1, 1)
        end_date = date(anchor, 12, 31)
    else:
        start_date = date(anchor[0], anchor[1], 1)
        end_date = date(anchor[0], anchor[1], calendar.monthrange(anchor[0], anchor[1])[1])
    return normalized, start_date, end_date


def _analytics_period_summary(period, reference):
    if period == "day":
        return f"Trong ngày {reference.strftime('%d/%m/%Y')}"
    if period == "year":
        return f"Trong năm {reference}"
    reference_year, reference_month = reference
    return f"Trong tháng {reference_month}/{reference_year}"


def _analytics_report_summary(period, reference, revenue_text):
    if period == "day":
        return f"Doanh thu ngày {reference.strftime('%d/%m/%Y')} là {revenue_text}đ."
    if period == "year":
        return f"Doanh thu năm {reference} là {revenue_text}đ."
    reference_year, reference_month = reference
    return f"Doanh thu tháng {reference_month}/{reference_year} là {revenue_text}đ."


def _build_pagination_pages(current_page, total_pages):
    if total_pages <= 4:
        return list(range(1, total_pages + 1))

    pages = [1, 2]
    left_window = max(3, current_page - 1)
    right_window = min(total_pages - 2, current_page + 1)

    if left_window > 3:
        pages.append("...")

    for page_num in range(left_window, right_window + 1):
        if page_num not in pages:
            pages.append(page_num)

    if right_window < total_pages - 2:
        pages.append("...")

    for page_num in [total_pages - 1, total_pages]:
        if page_num not in pages:
            pages.append(page_num)

    return pages


def _paginate(items, page=1, per_page=10, item_label="mục"):
    total_items = len(items)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    current_page = max(1, min(int(page or 1), total_pages))
    start = (current_page - 1) * per_page
    end = start + per_page
    return {
        "page": current_page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_prev": current_page > 1,
        "has_next": current_page < total_pages,
        "start_item": start + 1 if total_items else 0,
        "end_item": start + len(items[start:end]) if total_items else 0,
        "pages": _build_pagination_pages(current_page, total_pages),
        "item_label": item_label,
        "items": items[start:end],
    }


def _page_size_for(section_name, default=10):
    return SECTION_PAGE_SIZES.get(section_name, default)


def _build_account_item(user):
    customer_profile = getattr(user, "customer_profile", None)
    restaurant_profile = getattr(user, "restaurant_profile", None)
    role_label = ROLE_LABELS.get(user.role, 'Khác')
    extra_info = "-"
    if user.role == "customer" and customer_profile:
        extra_info = ", ".join(filter(None, [customer_profile.address or "", customer_profile.area or ""])) or "-"
    elif user.role == "restaurant" and restaurant_profile:
        extra_info = ", ".join(filter(None, [restaurant_profile.address or "", restaurant_profile.area or ""])) or "-"
    return {
        "user": user,
        "name": _safe_name(user),
        "role_label": role_label,
        "extra_info": extra_info,
        "created_vouchers": len(user.created_vouchers or []),
        "has_profile": bool(customer_profile or restaurant_profile),
    }


def _build_accounts(role_filter="all", query="", page=1, per_page=10):
    normalized_role = _normalize_role_filter(role_filter)
    q = User.query
    if normalized_role != "all":
        q = q.filter(User.role == normalized_role)
    if _clean(query):
        search = f"%{_clean(query)}%"
        q = q.filter(
            or_(
                User.username.ilike(search),
                User.display_name.ilike(search),
                User.email.ilike(search),
                User.phone.ilike(search),
            )
        )
    users = q.order_by(User.user_id.desc()).all()
    items = [_build_account_item(user) for user in users]

    stats = {
        "total": len(items),
        "customers": User.query.filter_by(role="customer").count(),
        "restaurants": User.query.filter_by(role="restaurant").count(),
        "admins": User.query.filter_by(role="admin").count(),
    }
    return {
        "records": _paginate(items, page=page, per_page=per_page, item_label="tài khoản"),
        "stats": stats,
        "role_filter": normalized_role,
        "search_query": query,
        "section_title": 'Quản lý tài khoản',
        "section_subtitle": 'Xem và kiểm soát tài khoản khách hàng, nhà hàng và quản trị.',
    }


def _build_voucher_item(voucher):
    creator = voucher.creator
    creator_role = ROLE_LABELS.get(creator.role, 'Tài khoản') if creator else 'Tài khoản'
    discount_text = '{:,}đ'.format(voucher.discount_value or 0)
    status_text = 'Đang bật' if voucher.status else 'Đang tắt'
    usage_count = len(voucher.orders or [])
    return {
        "voucher": voucher,
        "code": voucher.voucher_code or "",
        "creator_name": _safe_name(creator),
        "creator_role": creator_role,
        "discount_text": discount_text,
        "scope_text": 'Hệ thống' if voucher.voucher_scope == "system" else 'Nhà hàng',
        "status_text": status_text,
        "usage_count": usage_count,
        "start_date": format_vietnam_date(voucher.start_date) if voucher.start_date else 'Áp dụng ngay',
        "end_date": format_vietnam_date(voucher.end_date) if voucher.end_date else 'Không giới hạn',
    }


def _build_vouchers(query="", page=1, per_page=10):
    vouchers = Voucher.query.order_by(Voucher.voucher_id.desc()).all()
    items = []
    for voucher in vouchers:
        item = _build_voucher_item(voucher)
        if _match_query(
            voucher.voucher_code,
            voucher.voucher_scope,
            voucher.discount_type,
            voucher.discount_value,
            item["creator_name"],
            query=query,
        ):
            items.append(item)

    stats = {
        "total": len(items),
        "active": sum(1 for item in items if item["voucher"].status),
        "system": sum(1 for item in items if item["voucher"].voucher_scope == "system"),
        "restaurant": sum(1 for item in items if item["voucher"].voucher_scope == "restaurant"),
    }
    return {
        "records": _paginate(items, page=page, per_page=per_page, item_label="voucher"),
        "stats": stats,
        "search_query": query,
        "section_title": 'Quản lý voucher',
        "section_subtitle": 'Theo dõi toàn bộ voucher hệ thống và voucher của nhà hàng.',
    }


def _normalize_voucher_code(value):
    return re.sub(r"\s+", "", _clean(value)).upper()


def _parse_date_input(value):
    value = _clean(value)
    if not value:
        return None
    return date.fromisoformat(value)


def _validate_admin_voucher_form(form):
    voucher_code = _normalize_voucher_code(form.get("voucher_code"))
    discount_value_raw = _clean(form.get("discount_value"))
    start_date_raw = _clean(form.get("start_date"))
    end_date_raw = _clean(form.get("end_date"))
    errors = {}

    if not voucher_code:
        errors["voucher_code"] = 'Vui lòng nhập mã voucher.'
    elif len(voucher_code) > 50:
        errors["voucher_code"] = 'Mã voucher không được vượt quá 50 ký tự.'

    if not discount_value_raw:
        errors["discount_value"] = 'Vui lòng nhập giá trị giảm giá.'
    else:
        try:
            discount_value = int(discount_value_raw)
            if discount_value <= 0:
                raise ValueError
        except ValueError:
            errors["discount_value"] = 'Giá trị giảm phải là số nguyên lớn hơn 0.'

    start_date = None
    end_date = None
    try:
        start_date = _parse_date_input(start_date_raw) if start_date_raw else date.today()
    except ValueError:
        errors["start_date"] = 'Ngày bắt đầu không hợp lệ.'

    try:
        end_date = _parse_date_input(end_date_raw)
    except ValueError:
        errors["end_date"] = 'Ngày kết thúc không hợp lệ.'

    if start_date and end_date and end_date < start_date:
        errors["end_date"] = 'Ngày kết thúc phải sau hoặc bằng ngày bắt đầu.'

    if errors:
        raise ValueError(errors)

    return {
        "voucher_code": voucher_code,
        "discount_type": "amount",
        "discount_value": int(discount_value_raw),
        "start_date": start_date,
        "end_date": end_date,
        "status": form.get("status") == "on",
    }


def save_voucher_for_admin(user_id, form):
    admin = db.session.get(User, int(user_id)) if user_id else None
    if not admin or admin.role != "admin":
        raise ValueError({"user": 'Không tìm thấy tài khoản quản trị.'})

    data = _validate_admin_voucher_form(form)
    duplicate = Voucher.query.filter(db.func.upper(Voucher.voucher_code) == data["voucher_code"]).first()
    if duplicate:
        raise ValueError({"voucher_code": 'Mã voucher đã tồn tại.'})

    voucher = Voucher(created_by=admin.user_id, voucher_scope="system")
    voucher.voucher_code = data["voucher_code"]
    voucher.discount_type = data["discount_type"]
    voucher.discount_value = data["discount_value"]
    voucher.start_date = data["start_date"]
    voucher.end_date = data["end_date"]
    voucher.status = data["status"]
    voucher.voucher_scope = "system"
    db.session.add(voucher)
    db.session.commit()
    return voucher


def _build_review_item(review):
    restaurant_name = _safe_name(review.restaurant.user) if review.restaurant and review.restaurant.user else 'Chưa rõ'
    customer_name = _safe_name(review.customer.user) if review.customer and review.customer.user else 'Khách ẩn danh'
    return {
        "review": review,
        "restaurant_name": restaurant_name,
        "customer_name": customer_name,
        "created_at": _format_datetime(review.review_date),
        "rating_label": f"{review.rating or 0}/5",
        "report_status": review.report_status or "none",
        "report_reason": review.report_reason or "",
        "report_date": _format_datetime(review.report_date),
    }


def _build_reviews(query="", page=1, per_page=10):
    reviews = Review.query.order_by(Review.review_date.desc()).all()
    items = []
    for review in reviews:
        item = _build_review_item(review)
        if _match_query(review.comment, review.sentiment, item["restaurant_name"], item["customer_name"], query=query):
            items.append(item)

    stats = {
        "total": len(items),
        "positive": sum(1 for item in items if (item["review"].rating or 0) >= 4),
        "negative": sum(1 for item in items if (item["review"].rating or 0) <= 2),
    }
    return {
        "records": _paginate(items, page=page, per_page=per_page, item_label="đánh giá"),
        "stats": stats,
        "search_query": query,
        "section_title": 'Quản lý đánh giá',
        "section_subtitle": 'Duyệt nhanh các đánh giá gần đây từ khách hàng.',
    }


def _build_report_item(review):
    item = _build_review_item(review)
    item["severity"] = "Cao" if (review.rating or 0) <= 2 else 'Trung bình'
    item["report_note"] = item["report_reason"] or 'Nhà hàng báo cáo đánh giá này có dấu hiệu không chính xác.'
    return item


def _build_review_reports(query="", page=1, per_page=10):
    reviews = Review.query.filter(Review.report_status == "pending").order_by(Review.report_date.desc(), Review.review_date.desc()).all()
    items = []
    for review in reviews:
        item = _build_report_item(review)
        if _match_query(review.comment, review.report_reason, item["restaurant_name"], item["customer_name"], query=query):
            items.append(item)

    stats = {
        "total": len(items),
        "high": sum(1 for item in items if item["severity"] == "Cao"),
    }
    return {
        "records": _paginate(items, page=page, per_page=per_page, item_label="báo cáo"),
        "stats": stats,
        "search_query": query,
        "section_title": 'Báo cáo đánh giá',
        "section_subtitle": 'Các đánh giá bị nhà hàng báo cáo cần admin xem xét.',
    }


def _build_complaint_item(review):
    restaurant_name = _safe_name(review.restaurant.user) if review.restaurant and review.restaurant.user else 'Chưa rõ'
    customer_name = _safe_name(review.customer.user) if review.customer and review.customer.user else 'Khách ẩn danh'
    return {
        "review": review,
        "restaurant_name": restaurant_name,
        "customer_name": customer_name,
        "created_at": _format_datetime(review.review_date),
        "severity": "Cao" if (review.rating or 0) <= 1 else 'Trung bình',
    }


def _build_complaints(query="", page=1, per_page=10):
    reviews = Review.query.order_by(Review.review_date.desc()).all()
    items = []
    for review in reviews:
        if (review.rating or 0) <= 2 or _clean(review.sentiment).lower() in {"negative", "bad", "complaint"}:
            item = _build_complaint_item(review)
            if _match_query(review.comment, review.sentiment, item["restaurant_name"], item["customer_name"], query=query):
                items.append(item)

    stats = {
        "total": len(items),
        "high": sum(1 for item in items if item["severity"] == "Cao"),
    }
    return {
        "records": _paginate(items, page=page, per_page=per_page, item_label="khiếu nại"),
        "stats": stats,
        "search_query": query,
        "section_title": 'Khiếu nại',
        "section_subtitle": 'Các phản hồi tiêu cực cần theo dõi và xử lý sớm.',
    }


def _build_dispute_item(order):
    customer_name = _safe_name(order.customer.user) if order.customer and order.customer.user else 'Khách ẩn danh'
    restaurant_name = _safe_name(order.restaurant.user) if order.restaurant and order.restaurant.user else 'Chưa rõ'
    request_status = _clean(getattr(order, "cancel_request_status", "") or "").lower()
    request_reason = _clean(getattr(order, "cancel_request_reason", "") or "")
    admin_note = _clean(getattr(order, "cancel_request_admin_note", "") or "")
    handled_at = _format_datetime(getattr(order, "cancel_request_handled_at", None))
    order_status = _clean(order.status).lower()
    payment_method = _clean(getattr(order.payment, "payment_method", "") or "") if getattr(order, "payment", None) else ""
    payment_method_label = {
        "cash": "Tiền mặt",
        "momo": "MoMo",
    }.get(payment_method, payment_method or "Thanh toán")
    total_amount = max(0, int(getattr(order, "total_amount", 0) or 0))
    processed_statuses = {"approved", "rejected"}
    if request_status == "pending":
        status_label = "Chờ duyệt hủy"
        status_key = "cancel_request"
        filter_key = "unprocessed"
        type_key = "pending_cancel"
        type_label = "Yêu cầu hủy đơn"
    elif order_status in {"refund_pending", "pending_refund"}:
        status_label = "Chờ hoàn tiền"
        status_key = "refund_pending"
        filter_key = "unprocessed"
        type_key = "refund_pending"
        type_label = "Hoàn tiền"
    elif request_status in processed_statuses or order_status in {"cancelled", "canceled"}:
        status_label = "Đã xử lý"
        status_key = "processed"
        filter_key = "processed"
        type_key = "pending_cancel"
        type_label = "Yêu cầu hủy đơn"
    else:
        status_label = order.status or "unknown"
        status_key = order_status
        filter_key = "all"
        type_key = "pending_cancel"
        type_label = "Yêu cầu hủy đơn"
    reason_text = request_reason or admin_note or ("Đã xử lý" if status_label == "Đã xử lý" else "Chờ hoàn tiền")
    return {
        "order": order,
        "customer_name": customer_name,
        "restaurant_name": restaurant_name,
        "created_at": _format_datetime(order.order_date),
        "type_label": type_label,
        "type_key": type_key,
        "status_label": status_label,
        "status_key": status_key,
        "filter_key": filter_key,
        "request_pending": request_status == "pending",
        "request_reason": request_reason,
        "admin_note": admin_note,
        "handled_at": handled_at,
        "reason_text": reason_text,
        "detail_payload": {
            "order_id": order.order_id,
            "customer_name": customer_name,
            "restaurant_name": restaurant_name,
            "created_at": _format_datetime(order.order_date),
            "type_label": type_label,
            "type_key": type_key,
            "status_label": status_label,
            "status_key": status_key,
            "filter_key": filter_key,
            "request_pending": request_status == "pending",
            "request_reason": request_reason,
            "admin_note": admin_note,
            "handled_at": handled_at,
            "delivery_address": order.delivery_address or "Không có địa chỉ",
            "order_status": order.status or "unknown",
            "reason_text": reason_text,
            "payment_method_label": payment_method_label,
            "total_amount_text": _format_money(total_amount),
        },
    }


def _normalize_dispute_filter(value):
    value = _clean(value).lower() or "all"
    return value if value in {"all", "processed", "unprocessed", "refund_pending", "pending_cancel"} else "all"


def _normalize_dispute_type_filter(value):
    value = _clean(value).lower() or "all"
    return value if value in {"all", "refund_pending", "pending_cancel"} else "all"


def _normalize_dispute_state_filter(value):
    value = _clean(value).lower() or "all"
    return value if value in {"all", "processed", "unprocessed"} else "all"


def _build_disputes(query="", page=1, per_page=10, type_filter="all", state_filter="all"):
    type_filter = _normalize_dispute_type_filter(type_filter)
    state_filter = _normalize_dispute_state_filter(state_filter)
    orders = (
        Order.query.options(
            selectinload(Order.customer).selectinload(Customer.user),
            selectinload(Order.restaurant).selectinload(Restaurant.user),
        )
        .order_by(Order.order_date.desc(), Order.order_id.desc())
        .all()
    )
    items = []
    for order in orders:
        status_text = _clean(order.status).lower()
        request_status = _clean(getattr(order, "cancel_request_status", "") or "").lower()
        is_dispute_row = (
            request_status in {"pending", "approved", "rejected"}
            or status_text in {"refund_pending", "pending_refund"}
            or (status_text in {"cancelled", "canceled"} and request_status in {"approved", "rejected"})
        )
        if is_dispute_row:
            item = _build_dispute_item(order)
            item_filter_key = item.get("filter_key", "all")
            item_type_key = item.get("type_key", "pending_cancel")
            if type_filter != "all" and item_type_key != type_filter:
                continue
            if state_filter != "all" and item_filter_key != state_filter:
                continue
            if _match_query(
                order.delivery_address,
                order.status,
                item["customer_name"],
                item["restaurant_name"],
                item["request_reason"],
                item["admin_note"],
                item["status_label"],
                query=query,
            ):
                items.append(item)

    items.sort(key=lambda item: item["order"].order_id or 0, reverse=True)
    items.sort(key=lambda item: 0 if item.get("request_pending") else 1)

    stats = {
        "total": len(items),
        "pending_cancel_requests": sum(1 for item in items if item.get("request_pending")),
        "refund_pending": sum(1 for item in items if item.get("status_key") == "refund_pending"),
        "processed": sum(1 for item in items if item.get("filter_key") == "processed"),
        "unprocessed": sum(1 for item in items if item.get("filter_key") == "unprocessed"),
    }
    return {
        "records": _paginate(items, page=page, per_page=per_page, item_label="đơn"),
        "stats": stats,
        "search_query": query,
        "type_filter": type_filter,
        "state_filter": state_filter,
        "section_title": 'Hỗ trợ tranh chấp / hủy đơn',
        "section_subtitle": 'Theo dõi các đơn đang chờ duyệt hủy, chờ hoàn tiền hoặc đã xử lý.',
    }


def _build_restaurant_fee_item(restaurant):
    user = restaurant.user
    return {
        "restaurant": restaurant,
        "restaurant_name": _safe_name(user),
        "owner_name": _safe_name(user),
        "address": restaurant.address or "-",
        "area": restaurant.area or "-",
        "platform_fee": restaurant.platform_fee or 0,
        "platform_fee_text": _format_money(restaurant.platform_fee or 0),
        "has_profile": bool(restaurant.address or restaurant.area),
    }


def _build_restaurant_fees(query="", page=1, per_page=10):
    q = Restaurant.query.options(selectinload(Restaurant.user))
    if _clean(query):
        search = f"%{_clean(query)}%"
        q = q.join(User, User.user_id == Restaurant.restaurant_id).filter(
            or_(
                User.username.ilike(search),
                User.display_name.ilike(search),
                Restaurant.address.ilike(search),
                Restaurant.area.ilike(search),
                cast(Restaurant.platform_fee, String).ilike(search),
            )
        )

    restaurants = q.order_by(Restaurant.restaurant_id.desc()).all()
    items = [_build_restaurant_fee_item(restaurant) for restaurant in restaurants]
    area_options = [
        area
        for (area,) in (
            Restaurant.query.filter(Restaurant.area.isnot(None), Restaurant.area != "")
            .with_entities(Restaurant.area)
            .distinct()
            .order_by(Restaurant.area.asc())
            .all()
        )
        if _clean(area)
    ]
    total_fee = sum(item["platform_fee"] for item in items)
    configured_count = sum(1 for item in items if item["platform_fee"] > 0)
    average_fee = int(total_fee / len(items)) if items else 0

    return {
        "records": _paginate(items, page=page, per_page=per_page, item_label="nhà hàng"),
        "stats": {
            "total": len(items),
            "configured": configured_count,
            "unconfigured": max(0, len(items) - configured_count),
            "average_fee": average_fee,
        },
        "area_options": area_options,
        "search_query": query,
        "section_title": 'Phí sàn nhà hàng',
        "section_subtitle": 'Chỉnh phí sàn riêng cho từng nhà hàng. Checkout sẽ dùng đúng mức phí của nhà hàng đang thanh toán.',
    }


def _build_shipping_rules():
    rules = build_shipping_rules_form_values()
    settings = get_shipping_fee_settings()
    return {
        "records": _paginate([], page=1, per_page=1, item_label="phí"),
        "stats": {
            "floor_fee": settings.get("floor_fee", 0),
            "rules_count": len(rules),
        },
        "shipping_rules": rules,
        "section_title": 'Phí ship theo khoảng cách',
        "section_subtitle": "Cập nhật công thức tính phí ship dựa trên khoảng cách giữa nhà hàng và địa chỉ giao hàng của khách. Áp dụng cho tất cả đơn hàng có địa chỉ giao hàng nằm trong phạm vi áp dụng.",
    }

def _build_search_settings():
    search_radius_km = get_setting("SEARCH_RADIUS_KM", default=5)
    return {
        "records": _paginate([], page=1, per_page=1, item_label="cài đặt"),
        "stats": {
            "search_radius_km": search_radius_km,
        },
        "search_radius_km": search_radius_km,
        "section_title": 'Cài đặt tìm kiếm',
        "section_subtitle": 'Thiết lập bán kính tìm kiếm nhà hàng áp dụng cho hệ thống.',
    }


def _build_dashboard():
    users = User.query.all()
    orders = (
        Order.query.options(
            selectinload(Order.items),
            selectinload(Order.voucher),
            selectinload(Order.restaurant).selectinload(Restaurant.user),
        )
        .order_by(Order.order_date.desc(), Order.order_id.desc())
        .all()
    )

    today = date.today()
    _, month_start, month_end = _analytics_window_bounds("month", (today.year, today.month))

    order_status_counts = {"pending": 0, "preparing": 0, "shipping": 0, "completed": 0, "cancelled": 0, "other": 0}
    for order in orders:
        order_status_counts[_order_bucket(order.status)] += 1

    completed_orders = [order for order in orders if _order_bucket(order.status) == "completed"]
    monthly_completed_orders = []
    for order in completed_orders:
        order_date = getattr(order, "order_date", None)
        if not order_date:
            continue
        order_day = order_date.date()
        if month_start <= order_day <= month_end:
            monthly_completed_orders.append(order)

    monthly_revenue_summary = _build_revenue_summary(monthly_completed_orders)
    user_role_counts = {
        "customer": sum(1 for user in users if user.role == "customer"),
        "restaurant": sum(1 for user in users if user.role == "restaurant"),
        "admin": sum(1 for user in users if user.role == "admin"),
    }

    trend_days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    trend_order_map = {trend_day: 0 for trend_day in trend_days}
    trend_revenue_map = {trend_day: 0 for trend_day in trend_days}
    for order in orders:
        order_date = getattr(order, "order_date", None)
        if not order_date:
            continue
        order_day = order_date.date()
        if order_day not in trend_order_map:
            continue
        trend_order_map[order_day] += 1
        if _order_bucket(order.status) == "completed":
            trend_revenue_map[order_day] += _order_admin_revenue_breakdown(order)["net_admin_revenue"]

    restaurant_summary_map = {}
    for order in completed_orders:
        restaurant = getattr(order, "restaurant", None)
        restaurant_id = getattr(order, "restaurant_id", None)
        if not restaurant_id:
            continue
        if restaurant_id not in restaurant_summary_map:
            restaurant_summary_map[restaurant_id] = {
                "restaurant_name": _safe_name(restaurant.user) if restaurant and restaurant.user else f"NhÃ  hÃ ng #{restaurant_id}",
                "completed_orders": 0,
                "net_admin_revenue_total": 0,
            }
        restaurant_summary_map[restaurant_id]["completed_orders"] += 1
        restaurant_summary_map[restaurant_id]["net_admin_revenue_total"] += _order_admin_revenue_breakdown(order)["net_admin_revenue"]

    top_restaurants = sorted(
        restaurant_summary_map.values(),
        key=lambda item: (-item["completed_orders"], -item["net_admin_revenue_total"], item["restaurant_name"]),
    )[:5]

    pending_review_reports_count = Review.query.filter(Review.report_status == "pending").count()
    pending_cancel_requests_count = Order.query.filter(Order.cancel_request_status == "pending").count()
    negative_reviews_count = Review.query.filter((Review.rating <= 2) | (Review.sentiment.ilike("negative"))).count()

    latest_pending_review = (
        Review.query.options(selectinload(Review.restaurant).selectinload(Restaurant.user))
        .filter(Review.report_status == "pending")
        .order_by(Review.report_date.desc(), Review.review_date.desc(), Review.review_id.desc())
        .first()
    )
    latest_pending_cancel = (
        Order.query.options(selectinload(Order.restaurant).selectinload(Restaurant.user))
        .filter(Order.cancel_request_status == "pending")
        .order_by(Order.cancel_request_date.desc(), Order.order_date.desc(), Order.order_id.desc())
        .first()
    )
    latest_negative_review = (
        Review.query.options(selectinload(Review.restaurant).selectinload(Restaurant.user))
        .filter((Review.rating <= 2) | (Review.sentiment.ilike("negative")))
        .order_by(Review.review_date.desc(), Review.review_id.desc())
        .first()
    )

    total_orders = len(orders)
    completed_count = order_status_counts["completed"]
    cancelled_count = order_status_counts["cancelled"]

    return {
        "records": _paginate([], page=1, per_page=1, item_label="mục"),
        "stats": {
            "total_users": len(users),
            "customers": user_role_counts["customer"],
            "restaurants": user_role_counts["restaurant"],
            "admins": user_role_counts["admin"],
            "orders": total_orders,
            "completed_orders": completed_count,
            "cancelled_orders": cancelled_count,
            "completion_rate": _safe_percentage(completed_count, total_orders),
            "cancellation_rate": _safe_percentage(cancelled_count, total_orders),
            "pending_review_reports": pending_review_reports_count,
            "pending_cancel_requests": pending_cancel_requests_count,
            "negative_reviews": negative_reviews_count,
            "net_admin_revenue_month": monthly_revenue_summary["net_admin_revenue_total"],
        },
        "dashboard_chart_data": {
            "trend_chart": {
                "labels": [trend_day.strftime("%d/%m") for trend_day in trend_days],
                "orders": [trend_order_map[trend_day] for trend_day in trend_days],
                "revenue": [trend_revenue_map[trend_day] for trend_day in trend_days],
            },
            "order_status_chart": {
                "labels": ["Chờ xác nhận", "Đang chuẩn bị", "Đang giao", "Hoàn thành", "Đã hủy", "Khác"],
                "values": [
                    order_status_counts["pending"],
                    order_status_counts["preparing"],
                    order_status_counts["shipping"],
                    order_status_counts["completed"],
                    order_status_counts["cancelled"],
                    order_status_counts["other"],
                ],
                "colors": ["#f59e0b", "#fb7185", "#38bdf8", "#22c55e", "#94a3b8", "#cbd5e1"],
            },
            "top_restaurants_chart": {
                "labels": [item["restaurant_name"] for item in top_restaurants],
                "values": [item["completed_orders"] for item in top_restaurants],
                "revenue_values": [item["net_admin_revenue_total"] for item in top_restaurants],
                "color": "#ff8c1a",
            },
            "user_role_chart": {
                "labels": ["Khách hàng", "Nhà hàng", "Admin"],
                "values": [
                    user_role_counts["customer"],
                    user_role_counts["restaurant"],
                    user_role_counts["admin"],
                ],
                "colors": ["#4f74b8", "#f97316", "#a855f7"],
            },
        },
        "dashboard_alert_cards": [
            {
                "title": "Báo cáo đánh giá",
                "count": pending_review_reports_count,
                "description": (
                    f"Mới nhất từ {_safe_name(latest_pending_review.restaurant.user) if latest_pending_review and latest_pending_review.restaurant and latest_pending_review.restaurant.user else 'nhà hàng'}"
                    if latest_pending_review
                    else "Hiện không có báo cáo đánh giá nào đang chờ."
                ),
                "href": "admin.review_reports",
                "action_label": "Xem báo cáo",
                "tone": "warning",
            },
            {
                "title": "Yêu cầu hủy đơn",
                "count": pending_cancel_requests_count,
                "description": (
                    f"Đơn gần nhất #{latest_pending_cancel.order_id}" if latest_pending_cancel else "Không có yêu cầu hủy đơn đang chờ duyệt."
                ),
                "href": "admin.disputes",
                "action_label": "Mở tranh chấp",
                "tone": "info",
            },
            {
                "title": "Đánh giá tiêu cực",
                "count": negative_reviews_count,
                "description": (
                    f"Gần nhất từ {_safe_name(latest_negative_review.restaurant.user) if latest_negative_review and latest_negative_review.restaurant and latest_negative_review.restaurant.user else 'nhà hàng'}"
                    if latest_negative_review
                    else "Chưa có đánh giá tiêu cực cần theo dõi."
                ),
                "href": "admin.complaints",
                "action_label": "Xem khiếu nại",
                "tone": "soft",
            },
        ],
        "top_restaurants": top_restaurants,
        "dashboard_period_summary": f"Xu hướng 7 ngày gần nhất | Doanh thu tháng {today.month}/{today.year}: {_format_money_signed(monthly_revenue_summary['net_admin_revenue_total'])}",
        "section_title": "Dashboard quản trị",
        "section_subtitle": "Theo dõi sức khỏe hoạt động hệ thống, đơn hàng và các mục cần admin xử lý.",
    }


def _build_reports(period="month", report_date="", report_month="", report_year="", page=1):
    users = User.query.all()
    orders = (
        Order.query.options(
            selectinload(Order.items),
            selectinload(Order.voucher),
            selectinload(Order.restaurant).selectinload(Restaurant.user),
        )
        .order_by(Order.order_date.desc(), Order.order_id.desc())
        .all()
    )
    reviews = Review.query.all()
    vouchers = Voucher.query.all()

    normalized_period, reference = _analytics_period_reference(period, report_date, report_month, report_year)
    if normalized_period == "day":
        start_date, end_date = _analytics_window_bounds("day", reference)[1:]
    elif normalized_period == "year":
        start_date = date(reference, 1, 1)
        end_date = date(reference, 12, 31)
    else:
        start_date = date(reference[0], reference[1], 1)
        end_date = date(reference[0], reference[1], calendar.monthrange(reference[0], reference[1])[1])

    order_status_counts = {"pending": 0, "preparing": 0, "shipping": 0, "completed": 0, "cancelled": 0, "other": 0}
    for order in orders:
        order_status_counts[_order_bucket(order.status)] += 1

    completed_orders_list = [order for order in orders if _order_bucket(order.status) == "completed"]

    overall_revenue_summary = _build_revenue_summary(completed_orders_list)

    filtered_completed_orders_list = []
    for order in completed_orders_list:
        order_date = getattr(order, "order_date", None)
        if not order_date:
            continue
        order_day = order_date.date()
        if order_day < start_date or order_day > end_date:
            continue
        filtered_completed_orders_list.append(order)

    filtered_revenue_summary = _build_revenue_summary(filtered_completed_orders_list)
    order_revenue_items = []
    for order in filtered_completed_orders_list:
        breakdown = _order_admin_revenue_breakdown(order)
        order_revenue_items.append(
            {
                "order": order,
                "order_id": order.order_id,
                "restaurant_name": _safe_name(order.restaurant.user) if order.restaurant and order.restaurant.user else "Chưa rõ",
                "processing_fee_text": _format_money(breakdown["processing_fee"]),
                "restaurant_platform_fee_text": _format_money(breakdown["restaurant_platform_fee"]),
                "system_voucher_discount_text": _format_money(breakdown["system_voucher_discount"]),
                "merchant_voucher_discount_text": _format_money(breakdown["merchant_voucher_discount"]),
                "net_admin_revenue_text": _format_money_signed(breakdown["net_admin_revenue"]),
                "net_admin_revenue_value": breakdown["net_admin_revenue"],
                "platform_income_text": _format_money(breakdown["platform_income"]),
                "order_date_text": _format_datetime(order.order_date) if getattr(order, "order_date", None) else "Chưa rõ",
            }
        )

    user_role_counts = {
        "customer": sum(1 for user in users if user.role == "customer"),
        "restaurant": sum(1 for user in users if user.role == "restaurant"),
        "admin": sum(1 for user in users if user.role == "admin"),
    }

    pending_review_reports = Review.query.filter(Review.report_status == "pending").count()
    completed_orders = order_status_counts["completed"]
    cancelled_orders = order_status_counts["cancelled"]
    total_orders = len(orders) or 1
    page_data = _paginate(order_revenue_items, page=page, per_page=_page_size_for("reports", default=8), item_label="đơn")

    return {
        "records": page_data,
        "stats": {
            "users": len(users),
            "customers": user_role_counts["customer"],
            "restaurants": user_role_counts["restaurant"],
            "admins": user_role_counts["admin"],
            "orders": len(orders),
            "completed_orders": filtered_revenue_summary["completed_orders"],
            "total_completed_orders": completed_orders,
            "cancelled_orders": cancelled_orders,
            "processing_fee_total": filtered_revenue_summary["processing_fee_total"],
            "restaurant_platform_fee_total": filtered_revenue_summary["restaurant_platform_fee_total"],
            "gross_platform_income_total": filtered_revenue_summary["gross_platform_income_total"],
            "system_voucher_discount_total": filtered_revenue_summary["system_voucher_discount_total"],
            "merchant_voucher_discount_total": filtered_revenue_summary["merchant_voucher_discount_total"],
            "voucher_discount_total": filtered_revenue_summary["voucher_discount_total"],
            "net_admin_revenue_total": filtered_revenue_summary["net_admin_revenue_total"],
            "vouchers": len(vouchers),
            "reviews": len(reviews),
            "pending_review_reports": pending_review_reports,
            "completion_rate": _safe_percentage(completed_orders, total_orders),
            "cancellation_rate": _safe_percentage(cancelled_orders, total_orders),
            "filtered_completed_orders": filtered_revenue_summary["completed_orders"],
        },
        "report_data": {
            "order_status_chart": {
                "labels": ['Chờ xác nhận', 'Đang chuẩn bị', 'Đang giao', 'Hoàn thành', 'Đã hủy', 'Khác'],
                "values": [
                    order_status_counts["pending"],
                    order_status_counts["preparing"],
                    order_status_counts["shipping"],
                    order_status_counts["completed"],
                    order_status_counts["cancelled"],
                    order_status_counts["other"],
                ],
                "colors": ["#f59e0b", "#fb7185", "#38bdf8", "#22c55e", "#94a3b8", "#cbd5e1"],
            },
            "user_role_chart": {
                "labels": ['Khách hàng', 'Nhà hàng', "Admin"],
                "values": [
                    user_role_counts["customer"],
                    user_role_counts["restaurant"],
                    user_role_counts["admin"],
                ],
                "colors": ["#4f74b8", "#f97316", "#a855f7"],
            },
            "revenue_chart": {
                "labels": ['Phí xử lý 3000', 'Phí sàn nhà hàng', 'Giảm voucher hệ thống'],
                "values": [
                    filtered_revenue_summary["processing_fee_total"],
                    filtered_revenue_summary["restaurant_platform_fee_total"],
                    filtered_revenue_summary["system_voucher_discount_total"],
                ],
                "colors": ["#f59e0b", "#22c55e", "#ef4444"],
            },
        },
        "order_revenue_items": order_revenue_items,
        "report_filters": {
            "period": normalized_period,
            "date": report_date or (reference.isoformat() if normalized_period == "day" else ""),
            "month": report_month or (f"{reference[0]:04d}-{reference[1]:02d}" if normalized_period == "month" else ""),
            "year": report_year or (str(reference) if normalized_period == "year" else ""),
            "period_label": {
                "day": "Theo ngày",
                "month": "Theo tháng",
                "year": "Theo năm",
            }.get(normalized_period, "Theo tháng"),
            "period_summary": _analytics_period_summary(normalized_period, reference),
            "report_summary": _analytics_report_summary(normalized_period, reference, _format_money_signed(filtered_revenue_summary["net_admin_revenue_total"])),
        },
        "report_overview_stats": {
            "completed_orders": overall_revenue_summary["completed_orders"],
            "processing_fee_total": overall_revenue_summary["processing_fee_total"],
            "restaurant_platform_fee_total": overall_revenue_summary["restaurant_platform_fee_total"],
            "gross_platform_income_total": overall_revenue_summary["gross_platform_income_total"],
            "system_voucher_discount_total": overall_revenue_summary["system_voucher_discount_total"],
            "merchant_voucher_discount_total": overall_revenue_summary["merchant_voucher_discount_total"],
            "voucher_discount_total": overall_revenue_summary["voucher_discount_total"],
            "net_admin_revenue_total": overall_revenue_summary["net_admin_revenue_total"],
        },
        "section_title": 'Báo cáo thống kê',
        "section_subtitle": "Tổng hợp nhanh trạng thái đơn hàng, doanh thu phí nền tảng và ảnh hưởng của voucher.",
    }


def _build_hero_stats(section_name, dashboard_stats, context):
    if section_name == "dashboard":
        return [
            {"label": 'Tài khoản', "value": dashboard_stats["users"]},
            {"label": 'Nhà hàng', "value": dashboard_stats["restaurants"]},
            {"label": "Voucher", "value": dashboard_stats["vouchers"]},
            {"label": 'Đánh giá', "value": dashboard_stats["reviews"]},
            {"label": 'Báo cáo chờ xử lý', "value": dashboard_stats["pending_review_reports"]},
        ]

    stats = context.get("stats", {})
    if section_name == "accounts":
        return [
            {"label": 'Tổng tài khoản', "value": stats.get("total", 0)},
            {"label": 'Khách hàng', "value": stats.get("customers", 0)},
            {"label": 'Nhà hàng', "value": stats.get("restaurants", 0)},
            {"label": 'Quản trị viên', "value": stats.get("admins", 0)},
        ]

    if section_name == "vouchers":
        return [
            {"label": 'Tổng voucher', "value": stats.get("total", 0)},
            {"label": 'Đang bật', "value": stats.get("active", 0)},
            {"label": 'Hệ thống', "value": stats.get("system", 0)},
            {"label": 'Nhà hàng', "value": stats.get("restaurant", 0)},
        ]

    if section_name == "reviews":
        return [
            {"label": 'Tổng đánh giá', "value": stats.get("total", 0)},
            {"label": 'Tích cực', "value": stats.get("positive", 0)},
            {"label": 'Tiêu cực', "value": stats.get("negative", 0)},
        ]

    if section_name == "review_reports":
        return [
            {"label": 'Báo cáo chờ xử lý', "value": stats.get("total", 0)},
            {"label": 'Mức cao', "value": stats.get("high", 0)},
        ]

    if section_name == "complaints":
        return [
            {"label": 'Khiếu nại', "value": stats.get("total", 0)},
            {"label": 'Mức cao', "value": stats.get("high", 0)},
        ]

    if section_name == "disputes":
        return [
            {"label": 'Tranh chấp / hủy đơn', "value": stats.get("total", 0)},
            {"label": 'Đã xử lý', "value": stats.get("processed", 0)},
            {"label": 'Chưa xử lý', "value": stats.get("unprocessed", 0)},
            {"label": 'Chờ duyệt hủy', "value": stats.get("pending_cancel_requests", 0)},
            {"label": 'Chờ hoàn tiền', "value": stats.get("refund_pending", 0)},
        ]

    if section_name == "shipping_rules":
        return [
            {"label": 'Phí sàn hệ thống', "value": stats.get("floor_fee", 0), "suffix": 'đ'},
            {"label": 'Mức phí ship', "value": stats.get("rules_count", 0)},
        ]

    if section_name == "shipping_fees":
        return [
            {"label": 'Tổng nhà hàng', "value": stats.get("total", 0)},
            {"label": 'Đã cấu hình', "value": stats.get("configured", 0)},
            {"label": 'Chưa cấu hình', "value": stats.get("unconfigured", 0)},
            {"label": 'Phí trung bình', "value": stats.get("average_fee", 0), "suffix": 'đ'},
        ]

    if section_name == "search_settings":
        return [
            {"label": 'Bán kính tìm kiếm', "value": stats.get("search_radius_km", 5), "suffix": "km"},
        ]

    if section_name == "reports":
        report_stats = context.get("report_overview_stats", stats)
        return [
            {"label": "Tổng đơn hoàn thành", "value": report_stats.get("completed_orders", 0)},
            {"label": "Phí xử lý", "value": report_stats.get("processing_fee_total", 0), "suffix": "đ"},
            {"label": "Phí sàn NH", "value": report_stats.get("restaurant_platform_fee_total", 0), "suffix": "đ"},
            {"label": "Giảm voucher HT", "value": report_stats.get("system_voucher_discount_total", 0), "suffix": "đ"},
            {"label": "Doanh thu gộp", "value": report_stats.get("gross_platform_income_total", 0), "suffix": "đ"},
            {"label": "Doanh thu ròng", "value": report_stats.get("net_admin_revenue_total", 0), "suffix": "đ"},
        ]

    return []


def build_admin_context(section_name="dashboard", query="", role_filter="all", type_filter="all", state_filter="all", period="month", report_date="", report_month="", report_year="", page=1, per_page=10):
    section_name = section_name or "dashboard"
    page_size = _page_size_for(section_name, per_page)
    pending_review_reports = Review.query.filter(Review.report_status == "pending").count()
    pending_cancel_requests = Order.query.filter(Order.cancel_request_status == "pending").count()
    dashboard_stats = {
        "users": User.query.count(),
        "customers": User.query.filter_by(role="customer").count(),
        "restaurants": User.query.filter_by(role="restaurant").count(),
        "admins": User.query.filter_by(role="admin").count(),
        "vouchers": Voucher.query.count(),
        "reviews": Review.query.count(),
        "orders": Order.query.count(),
        "pending_cases": Review.query.filter((Review.rating <= 2) | (Review.sentiment.ilike("negative"))).count() + pending_review_reports + pending_cancel_requests,
        "pending_review_reports": pending_review_reports,
        "pending_cancel_requests": pending_cancel_requests,
    }

    if section_name == "dashboard":
        context = _build_dashboard()
    elif section_name == "accounts":
        context = _build_accounts(role_filter=role_filter, query=query, page=page, per_page=page_size)
    elif section_name == "vouchers":
        context = _build_vouchers(query=query, page=page, per_page=page_size)
    elif section_name == "reviews":
        context = _build_reviews(query=query, page=page, per_page=page_size)
    elif section_name == "complaints":
        context = _build_complaints(query=query, page=page, per_page=page_size)
    elif section_name == "review_reports":
        context = _build_review_reports(query=query, page=page, per_page=page_size)
    elif section_name == "disputes":
        context = _build_disputes(query=query, page=page, per_page=page_size, type_filter=type_filter, state_filter=state_filter)
    elif section_name == "shipping_fees":
        context = _build_restaurant_fees(query=query, page=page, per_page=page_size)
    elif section_name == "shipping_rules":
        context = _build_shipping_rules()
    elif section_name == "search_settings":
        context = _build_search_settings()
    elif section_name == "reports":
        context = _build_reports(period=period, report_date=report_date, report_month=report_month, report_year=report_year, page=page)
    else:
        context = {
            "records": _paginate([], page=page, per_page=per_page, item_label="mục"),
            "stats": dashboard_stats if section_name == "dashboard" else {},
            "search_query": query,
            "section_title": "Dashboard quản trị",
            "section_subtitle": "Tổng quan nhanh hệ thống, tài khoản và hoạt động gần đây.",
        }

    context["dashboard_stats"] = dashboard_stats
    context["hero_stats"] = _build_hero_stats(section_name, dashboard_stats, context)
    context["section_name"] = section_name
    return context
