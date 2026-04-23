import calendar
import os
import re
from datetime import date, datetime, timedelta

from flask import current_app, url_for
from sqlalchemy import bindparam, func
from sqlalchemy import inspect, text
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.customer import Customer
from app.models.dish import Dish
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.review import Review
from app.models.user import User
from app.models.voucher import Voucher
from app.models.restaurant import Restaurant
from app.services.order_state_service import refresh_simulated_order_state
from app.services.notification_service import (
    build_order_cancelled_notification,
    build_restaurant_cancel_request_notification,
    build_restaurant_cancel_request_result_notification,
    build_restaurant_review_report_notification,
    emit_structured_notification,
    emit_structured_notifications_to_users,
)
from app.utils.time_utils import format_vietnam_date, format_vietnam_datetime, to_vietnam_datetime, vietnam_now, vietnam_today


CATEGORY_RULES = [
    ("Cơm", ["cơm", "com", "rice", "sườn", "bì chả"]),
    ("Bún/Phở", ["bún", "bun", "phở", "pho", "hủ tiếu", "hu tieu"]),
    ("Khai vị", ["nem", "gỏi", "goi", "chả", "cha", "mực", "khoai"]),
    ("Đồ uống", ["cà phê", "ca phe", "trà", "tra", "nước", "nuoc", "soda", "pepsi", "coca"]),
    ("Món chính", ["gà", "ga", "bò", "bo", "heo", "thịt", "thit", "cá", "ca"]),
]

IMAGE_FALLBACKS = {
    "Cơm": "images/com-tam.jpg",
    "Bún/Phở": "images/nha_hang_pho.jpg",
    "Khai vị": "images/banh_xeo.jpg",
    "Đồ uống": "images/coca_cola.jpg",
    "Món chính": "images/ga_ran_popeyes.png",
    "Mặc định": "images/pizza_company.jpg",
}

VOUCHER_SCOPE_LABELS = {
    "system": "Hệ thống",
    "restaurant": "Nhà hàng",
}

VOUCHER_DISCOUNT_LABELS = {
    "amount": "Giảm",
}

EXCLUDED_ORDER_STATUSES = {"cancel", "canceled", "cancelled", "failed", "refund", "refund_pending", "pending_refund", "refunded", "rejected"}
COMPLETED_ORDER_STATUSES = {"completed", "delivered", "done"}


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slugify(text):
    normalized = _clean(text).lower()
    for src, dst in [
        ("á", "a"), ("à", "a"), ("ả", "a"), ("ã", "a"), ("ạ", "a"),
        ("ă", "a"), ("ắ", "a"), ("ằ", "a"), ("ẳ", "a"), ("ẵ", "a"), ("ặ", "a"),
        ("â", "a"), ("ấ", "a"), ("ầ", "a"), ("ẩ", "a"), ("ẫ", "a"), ("ậ", "a"),
        ("đ", "d"),
        ("é", "e"), ("è", "e"), ("ẻ", "e"), ("ẽ", "e"), ("ẹ", "e"),
        ("ê", "e"), ("ế", "e"), ("ề", "e"), ("ể", "e"), ("ễ", "e"), ("ệ", "e"),
        ("í", "i"), ("ì", "i"), ("ỉ", "i"), ("ĩ", "i"), ("ị", "i"),
        ("ó", "o"), ("ò", "o"), ("ỏ", "o"), ("õ", "o"), ("ọ", "o"),
        ("ô", "o"), ("ố", "o"), ("ồ", "o"), ("ổ", "o"), ("ỗ", "o"), ("ộ", "o"),
        ("ơ", "o"), ("ớ", "o"), ("ờ", "o"), ("ở", "o"), ("ỡ", "o"), ("ợ", "o"),
        ("ú", "u"), ("ù", "u"), ("ủ", "u"), ("ũ", "u"), ("ụ", "u"),
        ("ư", "u"), ("ứ", "u"), ("ừ", "u"), ("ử", "u"), ("ữ", "u"), ("ự", "u"),
        ("ý", "y"), ("ỳ", "y"), ("ỷ", "y"), ("ỹ", "y"), ("ỵ", "y"),
    ]:
        normalized = normalized.replace(src, dst)
    return normalized


def infer_category(dish):
    text = _slugify(f"{dish.dish_name or ''} {dish.description or ''}")
    for category, keywords in CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "Món chính"


def infer_image_path(category, dish):
    return IMAGE_FALLBACKS.get(category, IMAGE_FALLBACKS["Mặc định"])


RESTAURANT_ORDER_STATUS_MAP = {
    "pending": ("Chờ xác nhận", "is-pending", "pending"),
    "pending_payment": ("Chờ xác nhận", "is-pending", "pending"),
    "preparing": ("Đang chuẩn bị", "is-preparing", "preparing"),
    "refund_pending": ("Chờ hoàn tiền", "is-muted", "refund_pending"),
    "pending_refund": ("Chờ hoàn tiền", "is-muted", "refund_pending"),
    "ready_for_delivery": ("Chờ giao hàng", "is-warning", "shipping"),
    "waiting_delivery": ("Chờ giao hàng", "is-warning", "shipping"),
    "shipping": ("Đang giao hàng", "is-shipping", "shipping"),
    "completed": ("Hoàn thành", "is-success", "done"),
    "delivered": ("Hoàn thành", "is-success", "done"),
    "done": ("Hoàn thành", "is-success", "done"),
    "cancelled": ("Đã hủy", "is-muted", "cancelled"),
    "canceled": ("Đã hủy", "is-muted", "cancelled"),
}

RESTAURANT_ORDER_STATUS_FILTERS = {
    "all": None,
    "pending": {"pending", "pending_payment"},
    "preparing": {"preparing"},
    "waiting_shipping": {"ready_for_delivery", "waiting_delivery"},
    "shipping": {"shipping"},
    "completed": {"completed", "delivered", "done"},
    "cancelled": {"cancelled", "canceled"},
}


def _normalize_restaurant_order_status(order):
    raw_status = (order.status or "").strip().lower()
    status_label, status_class, status_key = RESTAURANT_ORDER_STATUS_MAP.get(
        raw_status,
        (order.status or "Chờ xác nhận", "is-info", "pending"),
    )
    return {
        "raw_status": raw_status,
        "label": status_label,
        "class": status_class,
        "key": status_key,
    }


def _format_order_code(order_id):
    return str(order_id) if order_id is not None else ""


def _format_money_vn(value):
    return "{:,}".format(max(0, int(value or 0))).replace(",", ".")


def _format_order_datetime(value):
    if not value:
        return ""
    return format_vietnam_date(value, "%d/%m/%Y %H:%M")


def _format_date_input(value):
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _build_order_item_preview(order_item, note_map=None):
    dish_name = order_item.dish.dish_name if order_item.dish else "Món ăn"
    quantity = max(1, int(order_item.quantity or 1))
    line_total = max(0, int((order_item.price or 0) * quantity))
    return {
        "name": dish_name,
        "quantity": quantity,
        "price": int(order_item.price or 0),
        "line_total": line_total,
        "note": (note_map or {}).get(order_item.order_item_id, getattr(order_item, "note", "") or ""),
    }


def _build_restaurant_order_view(order, note_map=None):
    status_info = _normalize_restaurant_order_status(order)
    items = [_build_order_item_preview(item, note_map=note_map) for item in (order.items or [])]
    payment_method = order.payment.payment_method if order.payment else ""
    payment_method_label = {
        "cash": "Tiền mặt",
        "momo": "MoMo",
    }.get((payment_method or "").strip().lower(), payment_method or "Thanh toán")
    payment_status = order.payment.status if order.payment else ""
    subtotal_amount = sum(item["line_total"] for item in items)
    delivery_fee_amount = max(0, int(order.delivery_fee or 0))
    total_before_discount = subtotal_amount + delivery_fee_amount
    total_amount = max(0, int(order.total_amount or 0))
    discount_amount = max(0, total_before_discount - total_amount)
    voucher = getattr(order, "voucher", None)
    voucher_code = (voucher.voucher_code or "").strip() if voucher else ""
    voucher_label = voucher_code or "Không áp dụng"
    discount_summary = f"-{_format_money_vn(discount_amount)}đ" if discount_amount else "0đ"
    customer_name = _safe_user_name(order.customer.user) if order.customer and order.customer.user else "Khách ẩn danh"
    cancel_reason = _clean(getattr(order, "cancel_reason", "") or "")
    cancel_request_status = _clean(getattr(order, "cancel_request_status", "") or "").lower()
    cancel_request_reason = _clean(getattr(order, "cancel_request_reason", "") or "")
    cancel_request_pending = cancel_request_status == "pending"
    shipping_started_at = getattr(order, "shipping_at", None) or order.order_date
    shipping_remaining_seconds = 0
    if status_info["key"] == "shipping" and shipping_started_at:
        shipping_remaining_seconds = max(0, int((shipping_started_at + timedelta(minutes=1) - vietnam_now()).total_seconds()))
    return {
        "order": order,
        "order_code": _format_order_code(order.order_id),
        "order_date_text": _format_order_datetime(order.order_date),
        "order_date_value": _format_date_input(order.order_date),
        "customer_name": customer_name,
        "delivery_address": order.delivery_address or "",
        "subtotal_amount_text": _format_money_vn(subtotal_amount),
        "delivery_fee_text": _format_money_vn(delivery_fee_amount),
        "discount_amount_text": discount_summary,
        "voucher_code": voucher_code,
        "voucher_label": voucher_label,
        "total_amount_text": _format_money_vn(total_amount),
        "status_label": status_info["label"],
        "status_class": status_info["class"],
        "status_key": status_info["key"],
        "status_raw": status_info["raw_status"],
        "cancel_reason": cancel_reason,
        "cancel_request_status": cancel_request_status,
        "cancel_request_reason": cancel_request_reason,
        "cancel_request_pending": cancel_request_pending,
        "payment_method_label": payment_method_label,
        "payment_status": payment_status or "",
        "shipping_remaining_seconds": shipping_remaining_seconds,
        "items": items,
        "item_count": sum(item["quantity"] for item in items),
        "detail_payload": {
            "order_code": _format_order_code(order.order_id),
            "order_id": order.order_id,
            "order_date_text": _format_order_datetime(order.order_date),
            "customer_name": customer_name,
            "delivery_address": order.delivery_address or "",
            "subtotal_amount_text": _format_money_vn(subtotal_amount),
            "delivery_fee_text": _format_money_vn(delivery_fee_amount),
            "discount_amount_text": discount_summary,
            "voucher_code": voucher_code,
            "voucher_label": voucher_label,
            "status_label": status_info["label"],
            "status_class": status_info["class"],
            "status_key": status_info["key"],
            "payment_method_label": payment_method_label,
            "payment_status": payment_status or "",
            "shipping_remaining_seconds": shipping_remaining_seconds,
            "total_amount_text": _format_money_vn(total_amount),
            "cancel_reason": cancel_reason,
            "cancel_request_status": cancel_request_status,
            "cancel_request_reason": cancel_request_reason,
            "items": items,
        },
    }


def _analytics_period_reference(period, date_value="", month_value="", year_value=""):
    today = vietnam_today()
    normalized_period = (period or "month").strip().lower()

    if normalized_period == "day":
        try:
            reference_date = date.fromisoformat(_clean(date_value)) if _clean(date_value) else today
        except ValueError:
            reference_date = today
        return normalized_period, reference_date

    if normalized_period == "year":
        try:
            reference_year = int(_clean(year_value) or today.year)
        except (TypeError, ValueError):
            reference_year = today.year
        return normalized_period, reference_year

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
    except (ValueError, TypeError):
        reference_year = today.year
        reference_month = today.month

    return "month", (reference_year, reference_month)


def _analytics_period_summary(period, reference):
    if period == "day":
        return f"Trong ngày {format_vietnam_date(reference, '%d/%m/%Y')}"
    if period == "year":
        return f"Trong năm {reference}"
    reference_year, reference_month = reference
    return f"Trong tháng {reference_month}/{reference_year}"


def _analytics_anchor_date(period, reference):
    if period == "day":
        return reference
    if period == "year":
        return date(reference, 12, 31)
    reference_year, reference_month = reference
    return date(reference_year, reference_month, calendar.monthrange(reference_year, reference_month)[1])


def _analytics_window_bounds(chart_period, anchor_date):
    normalized = (chart_period or "month").strip().lower()

    if normalized == "week":
        start_date = anchor_date - timedelta(days=6)
        end_date = anchor_date
    elif normalized == "year":
        start_date = date(anchor_date.year, 1, 1)
        end_date = date(anchor_date.year, 12, 31)
    else:
        start_date = date(anchor_date.year, anchor_date.month, 1)
        end_date = date(anchor_date.year, anchor_date.month, calendar.monthrange(anchor_date.year, anchor_date.month)[1])

    return normalized, start_date, end_date


def _analytics_report_summary(period, reference, revenue_text):
    if period == "day":
        return f"Doanh thu ngày {format_vietnam_date(reference, '%d/%m/%Y')} là {revenue_text}đ."
    if period == "year":
        return f"Doanh thu năm {reference} là {revenue_text}đ."
    reference_year, reference_month = reference
    return f"Doanh thu tháng {reference_month}/{reference_year} là {revenue_text}đ."


def _completed_order_timestamp(order):
    status = (order.status or "").strip().lower()
    if status not in COMPLETED_ORDER_STATUSES:
        return None

    if getattr(order, "shipping_at", None):
        return order.shipping_at + timedelta(minutes=1)
    return order.order_date


def _analytics_group_key(period, local_dt):
    if not local_dt:
        return None
    if period == "day":
        return local_dt.hour
    if period == "year":
        return local_dt.month
    return local_dt.day


def _analytics_bucket_definitions(period, reference):
    if period == "day":
        return [
            {
                "key": hour,
                "label": f"{hour:02d}h",
                "short_label": f"{hour:02d}",
                "orders": 0,
                "gross": 0,
                "net": 0,
                "platform_fee": 0,
                "voucher_discount": 0,
            }
            for hour in range(24)
        ]

    if period == "year":
        return [
            {
                "key": month,
                "label": f"T{month}",
                "short_label": f"T{month}",
                "orders": 0,
                "gross": 0,
                "net": 0,
                "platform_fee": 0,
                "voucher_discount": 0,
            }
            for month in range(1, 13)
        ]

    year, month = reference
    days = calendar.monthrange(year, month)[1]
    return [
        {
            "key": day,
            "label": f"{day}",
            "short_label": f"{day}",
            "orders": 0,
            "gross": 0,
            "net": 0,
            "platform_fee": 0,
            "voucher_discount": 0,
        }
        for day in range(1, days + 1)
    ]


def _build_line_chart_points(buckets):
    point_count = len(buckets)
    if not point_count:
        return "", []

    svg_points = []
    chart_points = []
    denominator = max(1, point_count - 1)

    for index, bucket in enumerate(buckets):
        x_percent = round((index / denominator) * 100, 2) if point_count > 1 else 50
        y_percent = round(100 - (bucket["height"] if bucket["net"] > 0 else 2), 2)
        svg_points.append(f"{x_percent},{y_percent}")
        chart_points.append(
            {
                **bucket,
                "x_percent": x_percent,
                "y_percent": y_percent,
            }
        )

    return " ".join(svg_points), chart_points


def _filter_completed_items_by_window(completed_items, start_date, end_date):
    filtered = []
    for item in completed_items:
        completed_at = item.get("completed_at")
        if not completed_at:
            continue
        completed_date = completed_at.date()
        if start_date <= completed_date <= end_date:
            filtered.append(item)
    return filtered


def _build_top_dish_analytics(completed_items):
    dish_totals = {}

    for item in completed_items:
        order = item["order"]
        for order_item in order.items or []:
            dish = getattr(order_item, "dish", None)
            dish_id = getattr(order_item, "dish_id", None) or getattr(dish, "dish_id", None)
            dish_name = (getattr(dish, "dish_name", "") or "Món ăn").strip()
            key = dish_id if dish_id is not None else f"name:{dish_name}"
            quantity = max(1, _safe_int(getattr(order_item, "quantity", 1), 1))
            line_total = max(0, _safe_int(getattr(order_item, "price", 0), 0) * quantity)

            record = dish_totals.setdefault(
                key,
                {
                    "key": key,
                    "name": dish_name,
                    "quantity": 0,
                    "revenue": 0,
                },
            )
            record["quantity"] += quantity
            record["revenue"] += line_total

    top_dishes = sorted(dish_totals.values(), key=lambda item: (item["quantity"], item["revenue"]), reverse=True)[:5]
    total_quantity = sum(item["quantity"] for item in top_dishes) or 1
    palette = ["#4f74b8", "#f97316", "#22c55e", "#eab308", "#a855f7"]

    labels = [item["name"] for item in top_dishes]
    values = [item["quantity"] for item in top_dishes]
    colors = palette[: len(top_dishes)]
    details = []

    for index, dish in enumerate(top_dishes, start=1):
        percentage = round((dish["quantity"] / total_quantity) * 100, 1) if total_quantity else 0
        details.append(
            {
                "rank": index,
                "name": dish["name"],
                "quantity": dish["quantity"],
                "percentage": percentage,
                "quantity_text": f"{dish['quantity']}",
                "percentage_text": f"{percentage:.1f}%",
                "revenue_text": _format_money_vn(dish["revenue"]),
                "color": colors[index - 1],
            }
        )

    return {
        "labels": labels,
        "values": values,
        "colors": colors,
        "details": details,
        "total_quantity": total_quantity,
    }


def _build_revenue_trend_analytics(completed_items, chart_period, anchor_date):
    normalized, start_date, end_date = _analytics_window_bounds(chart_period, anchor_date)
    window_items = _filter_completed_items_by_window(completed_items, start_date, end_date)

    if normalized == "week":
        buckets = []
        for index in range(7):
            day = start_date + timedelta(days=index)
            buckets.append(
                {
                    "key": day.isoformat(),
                    "label": format_vietnam_date(day, "%d/%m"),
                    "short_label": format_vietnam_date(day, "%d/%m"),
                    "orders": 0,
                    "gross": 0,
                    "net": 0,
                    "platform_fee": 0,
                    "voucher_discount": 0,
                    "day": day,
                }
            )
        bucket_map = {bucket["key"]: bucket for bucket in buckets}
        for item in window_items:
            bucket = bucket_map.get(item["completed_at"].date().isoformat())
            if not bucket:
                continue
            bucket["orders"] += 1
            bucket["gross"] += item["gross_amount"]
            bucket["net"] += item["net_revenue"]
            bucket["platform_fee"] += item["platform_fee_amount"]
            bucket["voucher_discount"] += item["merchant_voucher_discount"]
    elif normalized == "year":
        buckets = [
            {
                "key": month,
                "label": f"T{month}",
                "short_label": f"T{month}",
                "orders": 0,
                "gross": 0,
                "net": 0,
                "platform_fee": 0,
                "voucher_discount": 0,
            }
            for month in range(1, 13)
        ]
        bucket_map = {bucket["key"]: bucket for bucket in buckets}
        for item in window_items:
            bucket = bucket_map.get(item["completed_at"].month)
            if not bucket:
                continue
            bucket["orders"] += 1
            bucket["gross"] += item["gross_amount"]
            bucket["net"] += item["net_revenue"]
            bucket["platform_fee"] += item["platform_fee_amount"]
            bucket["voucher_discount"] += item["merchant_voucher_discount"]
    else:
        year, month = start_date.year, start_date.month
        days = calendar.monthrange(year, month)[1]
        buckets = [
            {
                "key": day,
                "label": f"{day}",
                "short_label": f"{day}",
                "orders": 0,
                "gross": 0,
                "net": 0,
                "platform_fee": 0,
                "voucher_discount": 0,
            }
            for day in range(1, days + 1)
        ]
        bucket_map = {bucket["key"]: bucket for bucket in buckets}
        for item in window_items:
            bucket = bucket_map.get(item["completed_at"].day)
            if not bucket:
                continue
            bucket["orders"] += 1
            bucket["gross"] += item["gross_amount"]
            bucket["net"] += item["net_revenue"]
            bucket["platform_fee"] += item["platform_fee_amount"]
            bucket["voucher_discount"] += item["merchant_voucher_discount"]

    labels = [bucket["label"] for bucket in buckets]
    revenue_values = [bucket["net"] for bucket in buckets]
    order_values = [bucket["orders"] for bucket in buckets]
    max_net = max(revenue_values, default=0) or 1
    if normalized == "week":
        title = "Doanh thu theo tuáº§n"
        subtitle = f"Từ {format_vietnam_date(start_date, '%d/%m')} đến {format_vietnam_date(end_date, '%d/%m/%Y')}."
    elif normalized == "year":
        title = f"Doanh thu theo tháng - Năm {start_date.year}"
        subtitle = "Mỗi điểm là doanh thu thực nhận của từng tháng."
    else:
        title = f"Doanh thu theo ngày - {format_vietnam_date(start_date, '%m/%Y')}"
        subtitle = "Mỗi điểm là doanh thu thực nhận của từng ngày trong tháng."

    return {
        "period": normalized,
        "title": title,
        "subtitle": subtitle,
        "labels": labels,
        "revenue_values": revenue_values,
        "order_values": order_values,
        "max_value": max_net,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


def _order_revenue_breakdown(order, restaurant):
    items = order.items or []
    subtotal_amount = sum(_safe_int(item.price, 0) * max(1, _safe_int(item.quantity, 1)) for item in items)
    delivery_fee_amount = max(0, _safe_int(order.delivery_fee, 0))
    total_amount = max(0, _safe_int(order.total_amount, 0))
    platform_fee_amount = max(0, _safe_int(getattr(restaurant, "platform_fee", 0), 0))
    discount_amount = max(0, subtotal_amount + delivery_fee_amount - total_amount)

    voucher = getattr(order, "voucher", None)
    voucher_scope = _clean(getattr(voucher, "voucher_scope", "")).lower() if voucher else ""
    merchant_voucher_discount = discount_amount if voucher and voucher_scope == "restaurant" and voucher.created_by == restaurant.restaurant_id else 0
    system_voucher_discount = discount_amount if voucher and voucher_scope == "system" else 0

    net_revenue = max(0, subtotal_amount - platform_fee_amount - merchant_voucher_discount)

    return {
        "subtotal_amount": subtotal_amount,
        "delivery_fee_amount": delivery_fee_amount,
        "total_amount": total_amount,
        "platform_fee_amount": platform_fee_amount,
        "discount_amount": discount_amount,
        "merchant_voucher_discount": merchant_voucher_discount,
        "system_voucher_discount": system_voucher_discount,
        "net_revenue": net_revenue,
        "voucher_code": (voucher.voucher_code or "").strip() if voucher else "",
        "voucher_scope": voucher_scope or "none",
    }


def _build_revenue_analytics_context(
    restaurant,
    period="month",
    analytics_date="",
    analytics_month="",
    analytics_year="",
    trend_period="month",
    top_period="month",
    page=1,
    per_page=7,
):
    normalized_period, reference = _analytics_period_reference(period, analytics_date, analytics_month, analytics_year)

    orders = (
        Order.query.filter_by(restaurant_id=restaurant.restaurant_id)
        .options(
            selectinload(Order.items),
            selectinload(Order.payment),
            selectinload(Order.voucher),
        )
        .order_by(Order.order_date.desc(), Order.order_id.desc())
        .all()
    )
    for order in orders:
        refresh_simulated_order_state(order)

    all_completed_items = []
    for order in orders:
        timestamp = _completed_order_timestamp(order)
        if not timestamp:
            continue

        local_dt = to_vietnam_datetime(timestamp)
        if not local_dt:
            continue

        revenue = _order_revenue_breakdown(order, restaurant)
        all_completed_items.append(
            {
                "order": order,
                "order_code": _format_order_code(order.order_id),
                "completed_at": local_dt,
                "completed_at_text": format_vietnam_datetime(local_dt, "%d/%m/%Y %H:%M"),
                "payment_method_label": {
                    "cash": "Tiền mặt",
                    "momo": "MoMo",
                }.get(((order.payment.payment_method if order.payment else "") or "").strip().lower(), "Thanh toán"),
                "customer_paid_text": _format_money_vn(revenue["total_amount"]),
                "gross_text": _format_money_vn(revenue["subtotal_amount"]),
                "platform_fee_text": _format_money_vn(revenue["platform_fee_amount"]),
                "voucher_discount_text": _format_money_vn(revenue["merchant_voucher_discount"]),
                "system_voucher_discount_text": _format_money_vn(revenue["system_voucher_discount"]),
                "net_revenue_text": _format_money_vn(revenue["net_revenue"]),
                "voucher_code": revenue["voucher_code"],
                "voucher_scope": revenue["voucher_scope"],
                "gross_amount": revenue["subtotal_amount"],
                "platform_fee_amount": revenue["platform_fee_amount"],
                "merchant_voucher_discount": revenue["merchant_voucher_discount"],
                "system_voucher_discount": revenue["system_voucher_discount"],
                "net_revenue": revenue["net_revenue"],
                "customer_paid_amount": revenue["total_amount"],
            }
        )

    all_completed_items.sort(
        key=lambda item: (
            item["completed_at"].timestamp() if item["completed_at"] else 0,
            item["order"].order_id or 0,
        ),
        reverse=True,
    )

    completed_items = []
    for item in all_completed_items:
        local_dt = item["completed_at"]
        if normalized_period == "day":
            if local_dt.date() != reference:
                continue
        elif normalized_period == "year":
            if local_dt.year != reference:
                continue
        else:
            reference_year, reference_month = reference
            if local_dt.year != reference_year or local_dt.month != reference_month:
                continue
        completed_items.append(item)

    total_completed = len(completed_items)
    total_pages = max(1, (total_completed + per_page - 1) // per_page) if per_page else 1
    current_page = max(1, min(_safe_int(page, 1), total_pages))
    start = (current_page - 1) * per_page if per_page else 0
    end = start + per_page if per_page else total_completed
    page_items = completed_items[start:end]

    pagination_pages = []
    if total_pages <= 4:
        pagination_pages = list(range(1, total_pages + 1))
    else:
        pagination_pages.extend([1, 2])
        left_window = max(3, current_page - 1)
        right_window = min(total_pages - 2, current_page + 1)
        if left_window > 3:
            pagination_pages.append("...")
        for page_num in range(left_window, right_window + 1):
            if page_num not in pagination_pages:
                pagination_pages.append(page_num)
        if right_window < total_pages - 2:
            pagination_pages.append("...")
        for page_num in [total_pages - 1, total_pages]:
            if page_num not in pagination_pages:
                pagination_pages.append(page_num)

    chart_anchor_date = vietnam_today()
    trend_chart = _build_revenue_trend_analytics(all_completed_items, trend_period, chart_anchor_date)

    top_anchor_date = chart_anchor_date
    top_normalized, top_start_date, top_end_date = _analytics_window_bounds(top_period, top_anchor_date)
    top_completed_items = _filter_completed_items_by_window(all_completed_items, top_start_date, top_end_date)
    top_dishes_chart = _build_top_dish_analytics(top_completed_items)
    top_dishes_chart["period"] = top_normalized
    top_dishes_chart["start_date"] = top_start_date.isoformat()
    top_dishes_chart["end_date"] = top_end_date.isoformat()

    trend_labels = {
        "week": "Theo tuần",
        "month": "Theo tháng",
        "year": "Theo năm",
    }
    top_labels = {
        "day": "Theo ngày",
        "week": "Theo tuần",
        "month": "Theo tháng",
        "year": "Theo năm",
    }
    trend_label = trend_labels.get((trend_period or "month").strip().lower(), "Theo tháng")
    top_label = top_labels.get((top_period or "month").strip().lower(), "Theo tháng")

    gross_total = sum(item["gross_amount"] for item in completed_items)
    platform_fee_total = sum(item["platform_fee_amount"] for item in completed_items)
    merchant_voucher_discount_total = sum(item["merchant_voucher_discount"] for item in completed_items)
    system_voucher_discount_total = sum(item["system_voucher_discount"] for item in completed_items)
    net_revenue_total = sum(item["net_revenue"] for item in completed_items)
    customer_paid_total = sum(item["customer_paid_amount"] for item in completed_items)
    average_order_value = round(customer_paid_total / total_completed) if total_completed else 0

    period_labels = {
        "day": "Theo ngày",
        "month": "Theo tháng",
        "year": "Theo năm",
    }
    if normalized_period == "day":
        reference_label = format_vietnam_date(reference, "%d/%m/%Y")
        chart_title = f"Doanh thu theo giờ - {reference_label}"
        chart_subtitle = "Mỗi cột là doanh thu thực nhận của từng khung giờ."
    elif normalized_period == "year":
        chart_title = f"Doanh thu theo tháng - Năm {reference}"
        chart_subtitle = "Mỗi cột là doanh thu thực nhận của từng tháng."
    else:
        reference_year, reference_month = reference
        month_reference = date(reference_year, reference_month, 1)
        chart_title = f"Doanh thu theo ngày - {format_vietnam_date(month_reference, '%m/%Y')}"
        chart_subtitle = "Mỗi cột là doanh thu thực nhận của từng ngày trong tháng."

    return {
        "restaurant": restaurant,
        "section_name": "analytics",
        "section_title": "Thống kê doanh thu",
        "section_subtitle": f"{_analytics_period_summary(normalized_period, reference)}. {_analytics_report_summary(normalized_period, reference, _format_money_vn(net_revenue_total))}",
        "stats": {
            "completed_orders": total_completed,
            "gross_revenue": gross_total,
            "platform_fee_total": platform_fee_total,
            "merchant_voucher_discount_total": merchant_voucher_discount_total,
            "system_voucher_discount_total": system_voucher_discount_total,
            "net_revenue": net_revenue_total,
            "customer_paid_total": customer_paid_total,
            "average_order_value": average_order_value,
        },
        "analytics_filters": {
            "period": normalized_period,
            "date": reference.isoformat() if normalized_period == "day" else _clean(analytics_date) or vietnam_today().isoformat(),
            "month": f"{reference[0]:04d}-{reference[1]:02d}" if normalized_period == "month" else _clean(analytics_month) or f"{vietnam_today().year:04d}-{vietnam_today().month:02d}",
            "year": str(reference) if normalized_period == "year" else _clean(analytics_year) or str(vietnam_today().year),
            "period_label": period_labels.get(normalized_period, "Theo tháng"),
            "period_summary": _analytics_period_summary(normalized_period, reference),
            "report_summary": _analytics_report_summary(normalized_period, reference, _format_money_vn(net_revenue_total)),
            "trend_period": (trend_period or "month").strip().lower(),
            "trend_label": trend_label,
            "top_period": (top_period or "month").strip().lower(),
            "top_label": top_label,
        },
        "chart": trend_chart,
        "trend_chart": trend_chart,
        "top_dishes_chart": top_dishes_chart,
        "items": page_items,
        "completed_count": total_completed,
        "pagination": {
            "page": current_page,
            "per_page": per_page,
            "total_items": total_completed,
            "total_pages": total_pages,
            "has_prev": current_page > 1,
            "has_next": current_page < total_pages,
            "start_item": start + 1 if total_completed else 0,
            "end_item": start + len(page_items) if total_completed else 0,
            "pages": pagination_pages,
        },
    }


def _orderitems_note_map(order_ids):
    if not order_ids:
        return {}

    try:
        inspector = inspect(db.engine)
        if not inspector.has_table("orderitems"):
            return {}
        columns = {column["name"] for column in inspector.get_columns("orderitems")}
    except Exception:
        return {}

    if "note" not in columns:
        return {}

    try:
        rows = db.session.execute(
            text("SELECT order_item_id, note FROM orderitems WHERE order_id IN :order_ids").bindparams(
                bindparam("order_ids", expanding=True)
            ),
            {"order_ids": list(order_ids)},
        ).mappings().all()
    except Exception:
        return {}

    return {row["order_item_id"]: row["note"] or "" for row in rows}


def _get_restaurant_dish_sales_map(restaurant_id):
    if not restaurant_id:
        return {}

    status_expr = func.lower(func.coalesce(Order.status, ""))
    total_rows = (
        db.session.query(
            OrderItem.dish_id.label("dish_id"),
            func.coalesce(func.sum(func.coalesce(OrderItem.quantity, 1)), 0).label("total_quantity"),
            func.min(func.date(Order.order_date)).label("first_order_date"),
        )
        .join(Order, Order.order_id == OrderItem.order_id)
        .join(Dish, Dish.dish_id == OrderItem.dish_id)
        .filter(Dish.restaurant_id == restaurant_id)
        .filter(Order.restaurant_id == restaurant_id)
        .filter(Order.order_date.isnot(None))
        .filter(~status_expr.in_(EXCLUDED_ORDER_STATUSES))
        .group_by(OrderItem.dish_id)
        .all()
    )

    today = date.today()
    today_rows = (
        db.session.query(
            OrderItem.dish_id.label("dish_id"),
            func.coalesce(func.sum(func.coalesce(OrderItem.quantity, 1)), 0).label("today_quantity"),
        )
        .join(Order, Order.order_id == OrderItem.order_id)
        .join(Dish, Dish.dish_id == OrderItem.dish_id)
        .filter(Dish.restaurant_id == restaurant_id)
        .filter(Order.restaurant_id == restaurant_id)
        .filter(Order.order_date.isnot(None))
        .filter(func.date(Order.order_date) == today)
        .filter(~status_expr.in_(EXCLUDED_ORDER_STATUSES))
        .group_by(OrderItem.dish_id)
        .all()
    )

    today_map = {row.dish_id: int(row.today_quantity or 0) for row in today_rows}
    sales_map = {}

    for row in total_rows:
        first_order_date = row.first_order_date
        if isinstance(first_order_date, str):
            try:
                first_order_date = date.fromisoformat(first_order_date)
            except ValueError:
                first_order_date = None

        total_quantity = int(row.total_quantity or 0)
        active_days = ((today - first_order_date).days + 1) if first_order_date else 0
        avg_day_orders = round(total_quantity / active_days) if active_days > 0 else 0

        sales_map[row.dish_id] = {
            "today_orders": today_map.get(row.dish_id, 0),
            "avg_day_orders": avg_day_orders,
        }

    for dish_id, today_orders in today_map.items():
        sales_map.setdefault(
            dish_id,
            {
                "today_orders": today_orders,
                "avg_day_orders": 0,
            },
        )

    return sales_map


def build_dish_view_model(dish, sales_map=None):
    category = dish.category or infer_category(dish)
    dish_id = dish.dish_id or 0
    sales_data = (sales_map or {}).get(dish_id, {})
    today_orders = int(sales_data.get("today_orders", 0) or 0)
    avg_day_orders = int(sales_data.get("avg_day_orders", 0) or 0)
    image_path = dish.image or infer_image_path(category, dish)
    performance_class = "is-up" if today_orders >= avg_day_orders else "is-down"

    return {
        "dish": dish,
        "category": category,
        "image_path": image_path,
        "today_orders": today_orders,
        "avg_day_orders": avg_day_orders,
        "performance_class": performance_class,
    }


def get_restaurant_by_user_id(user_id):
    if not user_id:
        return None
    try:
        return db.session.get(Restaurant, int(user_id))
    except (TypeError, ValueError):
        return None


def get_dish_for_restaurant(user_id, dish_id):
    restaurant = get_restaurant_by_user_id(user_id)
    if not restaurant:
        return None, None

    try:
        dish = db.session.get(Dish, int(dish_id))
    except (TypeError, ValueError):
        return restaurant, None

    if not dish or dish.restaurant_id != restaurant.restaurant_id:
        return restaurant, None

    return restaurant, dish


def get_voucher_for_restaurant(user_id, voucher_id):
    restaurant = get_restaurant_by_user_id(user_id)
    if not restaurant:
        return None, None

    try:
        voucher = db.session.get(Voucher, int(voucher_id))
    except (TypeError, ValueError):
        return restaurant, None

    if (
        not voucher
        or voucher.created_by != restaurant.restaurant_id
        or (voucher.voucher_scope or "restaurant") != "restaurant"
    ):
        return restaurant, None

    return restaurant, voucher


def _validate_dish_form(form):
    dish_name = _clean(form.get("dish_name"))
    category = _clean(form.get("category"))
    description = _clean(form.get("description"))
    price_raw = _clean(form.get("price"))
    errors = {}

    if not dish_name:
        errors["dish_name"] = "Vui lòng nhập tên món."
    elif len(dish_name) > 100:
        errors["dish_name"] = "Tên món không được vượt quá 100 ký tự."

    if not price_raw:
        errors["price"] = "Vui lòng nhập giá món."
    else:
        try:
            price = int(price_raw)
            if price <= 0:
                raise ValueError
        except ValueError:
            errors["price"] = "Giá món phải là số nguyên lớn hơn 0."

    if description and len(description) > 300:
        errors["description"] = "Mô tả không được vượt quá 300 ký tự."

    if category and len(category) > 80:
        errors["category"] = "Danh mục không được vượt quá 80 ký tự."

    if errors:
        raise ValueError(errors)

    return {
        "dish_name": dish_name,
        "category": category,
        "price": int(price_raw),
        "description": description,
        "status": form.get("status") == "on",
    }


def _normalize_voucher_code(value):
    return re.sub(r"\s+", "", _clean(value)).upper()


def _parse_date_input(value):
    value = _clean(value)
    if not value:
        return None
    return date.fromisoformat(value)


def _format_date_value(value):
    return value.isoformat() if value else ""


def _format_start_date_label(value):
    return format_vietnam_date(value) if value else "Áp dụng ngay"


def _format_end_date_label(value):
    return format_vietnam_date(value) if value else "Không giới hạn"


def _voucher_discount_text(voucher):
    discount_label = VOUCHER_DISCOUNT_LABELS["amount"]
    value = "{:,}đ".format(voucher.discount_value or 0)
    return f"{discount_label}: {value}"




def _voucher_state_info(voucher):
    today = vietnam_today()
    is_started = not voucher.start_date or voucher.start_date <= today
    not_expired = not voucher.end_date or voucher.end_date >= today

    if not is_started:
        return "Chưa áp dụng", "is-pending"
    if not not_expired:
        return "Đã hết hạn", "is-muted"
    if bool(voucher.status):
        return "Đang bật", "is-active"
    return "Đã tắt", "is-off"


def build_voucher_view_model(voucher, restaurant_id=None):
    status_text, status_class = _voucher_state_info(voucher)
    usage_count = len(voucher.orders or [])
    is_editable = (
        restaurant_id is not None
        and voucher.created_by == restaurant_id
        and (voucher.voucher_scope or "restaurant") == "restaurant"
    )

    return {
        "voucher": voucher,
        "code": voucher.voucher_code or "",
        "discount_text": _voucher_discount_text(voucher),
        "scope_text": VOUCHER_SCOPE_LABELS.get(voucher.voucher_scope or "restaurant", "Nhà hàng"),
        "status_text": status_text,
        "status_class": status_class,
        "usage_count": usage_count,
        "start_date_label": _format_start_date_label(voucher.start_date),
        "end_date_label": _format_end_date_label(voucher.end_date),
        "is_editable": is_editable,
        "is_active_now": bool(voucher.status) and status_class == "is-active",
    }


def _filter_voucher_views(voucher_views, query=""):
    query_slug = _slugify(query)
    if not query_slug:
        return voucher_views

    filtered = []
    for item in voucher_views:
        voucher = item["voucher"]
        searchable = " ".join(
            [
                voucher.voucher_code or "",
                voucher.discount_type or "",
                str(voucher.discount_value or ""),
                voucher.voucher_scope or "",
                item["status_text"],
                item["discount_text"],
            ]
        )
        if query_slug in _slugify(searchable):
            filtered.append(item)
    return filtered


def _validate_voucher_form(form):
    voucher_code = _normalize_voucher_code(form.get("voucher_code"))
    discount_value_raw = _clean(form.get("discount_value"))
    start_date_raw = _clean(form.get("start_date"))
    end_date_raw = _clean(form.get("end_date"))
    errors = {}

    if not voucher_code:
        errors["voucher_code"] = "Vui lòng nhập mã voucher."
    elif len(voucher_code) > 50:
        errors["voucher_code"] = "Mã voucher không được vượt quá 50 ký tự."

    if not discount_value_raw:
        errors["discount_value"] = "Vui lòng nhập giá trị giảm giá."
    else:
        try:
            discount_value = int(discount_value_raw)
            if discount_value <= 0:
                raise ValueError
        except ValueError:
            errors["discount_value"] = "Giá trị giảm giá phải là số nguyên lớn hơn 0."

    start_date = None
    end_date = None
    try:
        start_date = _parse_date_input(start_date_raw) if start_date_raw else vietnam_today()
    except ValueError:
        errors["start_date"] = "Ngày bắt đầu không hợp lệ."

    try:
        end_date = _parse_date_input(end_date_raw)
    except ValueError:
        errors["end_date"] = "Ngày kết thúc không hợp lệ."

    if start_date and end_date and end_date < start_date:
        errors["end_date"] = "Ngày kết thúc phải sau hoặc bằng ngày bắt đầu."

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


def _filter_dish_views(dish_views, query="", category="all"):
    query_slug = _slugify(query)
    filtered = dish_views

    if category and category != "all":
        filtered = [item for item in filtered if item["category"] == category]

    if query_slug:
        filtered = [
            item
            for item in filtered
            if query_slug in _slugify(item["dish"].dish_name or "")
            or query_slug in _slugify(item["dish"].description or "")
            or query_slug in _slugify(item["category"])
        ]

    return filtered




def build_dashboard_context(
    user_id,
    edit_dish_id=None,
    form_values=None,
    form_errors=None,
    query="",
    category="all",
    page=1,
    per_page=8,
):
    restaurant = get_restaurant_by_user_id(user_id)
    dishes = list(restaurant.dishes) if restaurant else []
    sales_map = _get_restaurant_dish_sales_map(restaurant.restaurant_id) if restaurant else {}
    edit_dish = None

    if edit_dish_id is not None and restaurant is not None:
        _, edit_dish = get_dish_for_restaurant(user_id, edit_dish_id)

    if form_values is None:
        if edit_dish:
            form_values = {
                "dish_name": edit_dish.dish_name or "",
                "category": edit_dish.category or infer_category(edit_dish),
                "price": edit_dish.price or "",
                "description": edit_dish.description or "",
                "status": "on" if edit_dish.status else "",
                "dish_id": edit_dish.dish_id,
                "image_name": edit_dish.image or "",
            }
        else:
            form_values = {
                "dish_name": "",
                "category": "",
                "price": "",
                "description": "",
                "status": "on",
                "dish_id": "",
                "image_name": "",
            }

    dish_views = [build_dish_view_model(dish, sales_map=sales_map) for dish in dishes]
    categories = []
    seen_categories = set()
    for item in dish_views:
        item_category = item["category"]
        if item_category not in seen_categories:
            categories.append(item_category)
            seen_categories.add(item_category)

    filtered_dish_views = _filter_dish_views(dish_views, query=query, category=category)
    total_items = len(filtered_dish_views)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    current_page = max(1, min(int(page or 1), total_pages))
    start = (current_page - 1) * per_page
    end = start + per_page
    paged_dish_views = filtered_dish_views[start:end]

    pagination_pages = []
    if total_pages <= 4:
        pagination_pages = list(range(1, total_pages + 1))
    else:
        pagination_pages.extend([1, 2])
        left_window = max(3, current_page - 1)
        right_window = min(total_pages - 2, current_page + 1)
        if left_window > 3:
            pagination_pages.append("...")
        for page_num in range(left_window, right_window + 1):
            if page_num not in pagination_pages:
                pagination_pages.append(page_num)
        if right_window < total_pages - 2:
            pagination_pages.append("...")
        for page_num in [total_pages - 1, total_pages]:
            if page_num not in pagination_pages:
                pagination_pages.append(page_num)

    stats = {
        "total": len(dish_views),
        "active": sum(1 for item in dish_views if item["dish"].status),
        "inactive": sum(1 for item in dish_views if not item["dish"].status),
        "categories": len(categories),
        "filtered": total_items,
    }

    return {
        "restaurant": restaurant,
        "dishes": dishes,
        "dish_views": dish_views,
        "paged_dish_views": paged_dish_views,
        "categories": categories,
        "edit_dish": edit_dish,
        "form_values": form_values,
        "form_errors": form_errors or {},
        "stats": stats,
        "search_query": query,
        "active_category": category or "all",
        "pagination": {
            "page": current_page,
            "per_page": per_page,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_prev": current_page > 1,
            "has_next": current_page < total_pages,
            "start_item": start + 1 if total_items else 0,
            "end_item": start + len(paged_dish_views) if total_items else 0,
            "pages": pagination_pages,
        },
    }


def _safe_user_name(user):
    if not user:
        return "Khách ẩn danh"
    return user.display_name or user.username or "Khách ẩn danh"


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


def build_voucher_section_context(
    user_id,
    edit_voucher_id=None,
    form_values=None,
    form_errors=None,
    query="",
    page=1,
    per_page=7,
):
    restaurant = get_restaurant_by_user_id(user_id)
    if not restaurant:
        return {
            "restaurant": None,
            "section_name": "vouchers",
            "section_title": "Chưa có hồ sơ nhà hàng",
            "section_subtitle": "Vui lòng hoàn thiện thông tin nhà hàng trước.",
            "items": [],
            "stats": {},
        }

    vouchers = (
        Voucher.query.filter_by(created_by=restaurant.restaurant_id, voucher_scope="restaurant")
        .order_by(Voucher.voucher_id.desc())
        .all()
    )
    voucher_views = [build_voucher_view_model(voucher, restaurant.restaurant_id) for voucher in vouchers]
    voucher_views = _filter_voucher_views(voucher_views, query=query)
    total_items = len(voucher_views)
    total_pages = max(1, (total_items + per_page - 1) // per_page) if per_page else 1
    current_page = max(1, min(_safe_int(page, 1), total_pages))
    start = (current_page - 1) * per_page if per_page else 0
    end = start + per_page if per_page else total_items
    paged_voucher_views = voucher_views[start:end]

    edit_voucher = None
    if edit_voucher_id is not None:
        _, edit_voucher = get_voucher_for_restaurant(user_id, edit_voucher_id)

    if form_values is None:
        if edit_voucher:
            form_values = {
                "voucher_id": edit_voucher.voucher_id,
                "voucher_code": edit_voucher.voucher_code or "",
                "discount_type": "amount",
                "discount_value": edit_voucher.discount_value or "",
                "start_date": _format_date_value(edit_voucher.start_date),
                "end_date": _format_date_value(edit_voucher.end_date),
                "status": "on" if edit_voucher.status else "",
                "voucher_scope": edit_voucher.voucher_scope or "restaurant",
            }
        else:
            form_values = {
                "voucher_id": "",
                "voucher_code": "",
                "discount_type": "amount",
                "discount_value": "",
                "start_date": vietnam_today().isoformat(),
                "end_date": "",
                "status": "on",
                "voucher_scope": "restaurant",
            }


    if not _clean((form_values or {}).get("start_date")):
        form_values = dict(form_values or {})
        form_values["start_date"] = vietnam_today().isoformat()

    today = vietnam_today()
    stats = {
        "total_vouchers": len(voucher_views),
        "active_vouchers": sum(1 for item in voucher_views if item["status_class"] == "is-active"),
        "expiring_soon": sum(
            1
            for item in voucher_views
            if item["voucher"].end_date
            and today <= item["voucher"].end_date
            and (item["voucher"].end_date - today).days <= 7
        ),
        "used_vouchers": sum(1 for item in voucher_views if item["usage_count"] > 0),
    }

    return {
        "restaurant": restaurant,
        "section_name": "vouchers",
        "section_title": "Quản lý voucher",
        "section_subtitle": "Tạo, bật/tắt và cập nhật các voucher của nhà hàng.",
        "items": paged_voucher_views,
        "stats": stats,
        "edit_voucher": edit_voucher,
        "form_values": form_values,
        "form_errors": form_errors or {},
        "search_query": query,
        "pagination": {
            "page": current_page,
            "per_page": per_page,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_prev": current_page > 1,
            "has_next": current_page < total_pages,
            "start_item": start + 1 if total_items else 0,
            "end_item": start + len(paged_voucher_views) if total_items else 0,
            "pages": _build_pagination_pages(current_page, total_pages),
        },
    }


def build_section_context(
    user_id,
    section_name,
    edit_voucher_id=None,
    form_values=None,
    form_errors=None,
    query="",
    order_status="all",
    sort="desc",
    date_from="",
    date_to="",
    focus_order_id=None,
    page=1,
    per_page=10,
    analytics_period="month",
    analytics_date="",
    analytics_month="",
    analytics_year="",
    analytics_trend_period="month",
    analytics_top_period="month",
):
    restaurant = get_restaurant_by_user_id(user_id)
    if not restaurant:
        return {
            "restaurant": None,
            "section_name": section_name,
            "section_title": "Chưa có hồ sơ nhà hàng",
            "section_subtitle": "Vui lòng hoàn thiện thông tin nhà hàng trước.",
            "items": [],
            "stats": {},
        }

    section_name = section_name or "orders"
    if section_name == "reviews":
        reviews = (
            Review.query.filter_by(restaurant_id=restaurant.restaurant_id)
            .order_by(Review.review_date.desc())
            .all()
        )
        items = []
        ratings = []
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
                    "report_status": review.report_status or "none",
                    "report_reason": review.report_reason or "",
                }
            )
            if review.rating is not None:
                ratings.append(review.rating)

        total_items = len(items)
        total_pages = max(1, (total_items + per_page - 1) // per_page) if per_page else 1
        current_page = max(1, min(_safe_int(page, 1), total_pages))
        start = (current_page - 1) * per_page if per_page else 0
        end = start + per_page if per_page else total_items
        paged_items = items[start:end]

        average_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0
        stats = {
            "total_reviews": len(items),
            "average_rating": average_rating,
            "positive_reviews": sum(1 for item in items if (item["review"].rating or 0) >= 4),
        }
        return {
            "restaurant": restaurant,
            "section_name": section_name,
            "section_title": "Xem các đánh giá nhà hàng",
            "section_subtitle": "Theo dõi nhận xét của khách hàng và phản hồi kịp thời.",
            "items": paged_items,
            "stats": stats,
            "pagination": {
                "page": current_page,
                "per_page": per_page,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_prev": current_page > 1,
                "has_next": current_page < total_pages,
                "start_item": start + 1 if total_items else 0,
                "end_item": start + len(paged_items) if total_items else 0,
                "pages": _build_pagination_pages(current_page, total_pages),
            },
        }

    if section_name == "orders":
        orders = (
            Order.query.filter_by(restaurant_id=restaurant.restaurant_id)
            .options(
                selectinload(Order.items).selectinload(OrderItem.dish),
                selectinload(Order.customer).selectinload(Customer.user),
                selectinload(Order.payment),
                selectinload(Order.voucher),
            )
            .order_by(Order.order_date.desc(), Order.order_id.desc())
            .all()
        )
        for order in orders:
            refresh_simulated_order_state(order)
        note_map = _orderitems_note_map([order.order_id for order in orders])

        search_term = _clean(query).lower()
        status_filter = (order_status or "all").strip().lower()
        valid_statuses = RESTAURANT_ORDER_STATUS_FILTERS.get(status_filter)
        start_date = None
        end_date = None
        if _clean(date_from):
            try:
                start_date = date.fromisoformat(_clean(date_from))
            except ValueError:
                start_date = None
        if _clean(date_to):
            try:
                end_date = date.fromisoformat(_clean(date_to))
            except ValueError:
                end_date = None

        overview_items = []
        filtered_items = []
        for order in orders:
            order_view = _build_restaurant_order_view(order, note_map=note_map)
            order_date_only = order.order_date.date() if order.order_date else None
            if start_date and order_date_only and order_date_only < start_date:
                continue
            if end_date and order_date_only and order_date_only > end_date:
                continue

            overview_items.append(order_view)

            if search_term:
                searchable = " ".join(
                    [
                        order_view["order_code"],
                        order_view["customer_name"],
                        order_view["delivery_address"],
                        str(order.order_id or ""),
                    ]
                ).lower()
                if search_term not in searchable:
                    continue

            if valid_statuses is not None and order_view["status_raw"] not in valid_statuses:
                continue

            filtered_items.append(order_view)

        sort_direction = (sort or "desc").strip().lower()
        filtered_items.sort(
            key=lambda item: (
                item["order"].order_date or datetime.min,
                item["order"].order_id or 0,
            ),
            reverse=sort_direction != "asc",
        )

        total_items = len(filtered_items)
        total_pages = max(1, (total_items + per_page - 1) // per_page) if per_page else 1
        current_page = max(1, min(int(page or 1), total_pages))
        start = (current_page - 1) * per_page if per_page else 0
        end = start + per_page if per_page else total_items
        items = filtered_items[start:end]

        pagination_pages = []
        if total_pages <= 4:
            pagination_pages = list(range(1, total_pages + 1))
        else:
            pagination_pages.extend([1, 2])
            left_window = max(3, current_page - 1)
            right_window = min(total_pages - 2, current_page + 1)
            if left_window > 3:
                pagination_pages.append("...")
            for page_num in range(left_window, right_window + 1):
                if page_num not in pagination_pages:
                    pagination_pages.append(page_num)
            if right_window < total_pages - 2:
                pagination_pages.append("...")
            for page_num in [total_pages - 1, total_pages]:
                if page_num not in pagination_pages:
                    pagination_pages.append(page_num)

        stats = {
            "total_orders": len(overview_items),
            "completed_orders": sum(1 for item in overview_items if item["status_key"] == "done"),
            "shipping_orders": sum(1 for item in overview_items if item["status_key"] == "shipping"),
            "pending_orders": sum(1 for item in overview_items if item["status_key"] == "pending"),
            "preparing_orders": sum(1 for item in overview_items if item["status_key"] == "preparing"),
            "cancel_request_pending_orders": sum(1 for item in overview_items if item["cancel_request_pending"]),
            "cancelled_orders": sum(1 for item in overview_items if item["status_key"] == "cancelled"),
        }

        tab_counts = {
            "all": len(overview_items),
            "pending": sum(1 for item in overview_items if item["status_key"] == "pending"),
            "preparing": sum(1 for item in overview_items if item["status_key"] == "preparing"),
            "waiting_shipping": sum(
                1
                for item in overview_items
                if item["status_key"] == "shipping" and item["status_raw"] in {"ready_for_delivery", "waiting_delivery"}
            ),
            "shipping": sum(1 for item in overview_items if item["status_key"] == "shipping" and item["status_raw"] == "shipping"),
            "completed": sum(1 for item in overview_items if item["status_key"] == "done"),
            "cancelled": sum(1 for item in overview_items if item["status_key"] == "cancelled"),
        }

        return {
            "restaurant": restaurant,
            "section_name": section_name,
            "section_title": "Quản lý đơn hàng mới",
            "section_subtitle": "Quản lý danh sách đơn hàng mới của nhà hàng.",
            "items": items,
            "stats": stats,
            "order_filters": {
                "q": query,
                "status": status_filter,
                "sort": sort_direction,
                "date_from": _clean(date_from),
                "date_to": _clean(date_to),
                "focus_order_id": focus_order_id,
            },
            "order_status_tabs": [
                {"key": "all", "label": "Tất cả", "count": tab_counts["all"]},
                {"key": "pending", "label": "Chờ xác nhận", "count": tab_counts["pending"]},
                {"key": "preparing", "label": "Đang chuẩn bị", "count": tab_counts["preparing"]},
                {"key": "waiting_shipping", "label": "Chờ giao hàng", "count": tab_counts["waiting_shipping"]},
                {"key": "shipping", "label": "Đang giao hàng", "count": tab_counts["shipping"]},
                {"key": "completed", "label": "Hoàn thành", "count": tab_counts["completed"]},
            ],
            "shown_count": len(items),
            "pagination": {
                "page": current_page,
                "per_page": per_page,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_prev": current_page > 1,
                "has_next": current_page < total_pages,
                "start_item": start + 1 if total_items else 0,
                "end_item": start + len(items) if total_items else 0,
                "pages": pagination_pages,
            },
        }

    if section_name == "vouchers":
        return build_voucher_section_context(
            user_id,
            edit_voucher_id=edit_voucher_id,
            form_values=form_values,
            form_errors=form_errors,
            query=query,
            page=page,
            per_page=7,
        )

    if section_name == "analytics":
        return _build_revenue_analytics_context(
            restaurant,
            period=analytics_period,
            analytics_date=analytics_date,
            analytics_month=analytics_month,
            analytics_year=analytics_year,
            trend_period=analytics_trend_period,
            top_period=analytics_top_period,
            page=page,
            per_page=7,
        )

    orders = (
        Order.query.filter_by(restaurant_id=restaurant.restaurant_id)
        .order_by(Order.order_date.desc())
        .all()
    )
    total_revenue = sum(order.total_amount or 0 for order in orders)
    recent_reviews = Review.query.filter_by(restaurant_id=restaurant.restaurant_id).all()
    avg_rating = (
        round(sum(review.rating or 0 for review in recent_reviews) / len(recent_reviews), 1)
        if recent_reviews
        else 0
    )
    stats = {
        "revenue": total_revenue,
        "orders": len(orders),
        "reviews": len(recent_reviews),
        "average_rating": avg_rating,
    }
    items = []
    return {
        "restaurant": restaurant,
        "section_name": section_name,
        "section_title": "Thống kê doanh thu và báo cáo",
        "section_subtitle": "Tổng hợp nhanh doanh thu, số đơn và đánh giá.",
        "items": items,
        "stats": stats,
    }


def save_dish_for_restaurant(user_id, form, file_storage=None):
    restaurant = get_restaurant_by_user_id(user_id)
    if not restaurant:
        raise ValueError({"restaurant": "Không tìm thấy hồ sơ nhà hàng."})

    data = _validate_dish_form(form)
    dish_id = _clean(form.get("dish_id"))
    action = "created"

    if dish_id:
        _, dish = get_dish_for_restaurant(user_id, dish_id)
        if not dish:
            raise ValueError({"dish_id": "Món ăn không tồn tại hoặc không thuộc nhà hàng của bạn."})
        action = "updated"
    else:
        dish = Dish(restaurant_id=restaurant.restaurant_id)
        db.session.add(dish)

    dish.dish_name = data["dish_name"]
    dish.category = data["category"] or dish.category or infer_category(dish)
    dish.price = data["price"]
    dish.description = data["description"]
    dish.status = data["status"]

    if file_storage and getattr(file_storage, "filename", ""):
        filename = secure_filename(file_storage.filename)
        upload_dir = os.path.join(current_app.static_folder, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        file_storage.save(os.path.join(upload_dir, filename))
        dish.image = f"uploads/{filename}"

    db.session.commit()

    return dish, action


def save_voucher_for_restaurant(user_id, form):
    restaurant = get_restaurant_by_user_id(user_id)
    if not restaurant:
        raise ValueError({"restaurant": "Không tìm thấy hồ sơ nhà hàng."})

    data = _validate_voucher_form(form)
    voucher_id = _clean(form.get("voucher_id"))
    action = "created"

    if voucher_id:
        _, voucher = get_voucher_for_restaurant(user_id, voucher_id)
        if not voucher:
            raise ValueError({"voucher_id": "Voucher không tồn tại hoặc không thuộc nhà hàng của bạn."})
        action = "updated"
        duplicate = (
            Voucher.query.filter(db.func.upper(Voucher.voucher_code) == data["voucher_code"])
            .filter(Voucher.voucher_id != voucher.voucher_id)
            .first()
        )
    else:
        duplicate = (
            Voucher.query.filter(db.func.upper(Voucher.voucher_code) == data["voucher_code"]).first()
        )
        if duplicate:
            raise ValueError({"voucher_code": "Mã voucher đã tồn tại."})

        voucher = Voucher(created_by=restaurant.restaurant_id, voucher_scope="restaurant")
        db.session.add(voucher)

    if duplicate:
        raise ValueError({"voucher_code": "Mã voucher đã tồn tại."})

    voucher.voucher_code = data["voucher_code"]
    voucher.discount_type = "amount"
    voucher.discount_value = data["discount_value"]
    voucher.start_date = data["start_date"]
    voucher.end_date = data["end_date"]
    voucher.status = data["status"]
    voucher.voucher_scope = "restaurant"
    voucher.created_by = restaurant.restaurant_id

    db.session.commit()
    return voucher, action


def toggle_dish_status_for_restaurant(user_id, dish_id):
    restaurant, dish = get_dish_for_restaurant(user_id, dish_id)
    if not restaurant or not dish:
        return None

    dish.status = not bool(dish.status)
    db.session.commit()
    return dish


def toggle_voucher_status_for_restaurant(user_id, voucher_id):
    restaurant, voucher = get_voucher_for_restaurant(user_id, voucher_id)
    if not restaurant or not voucher:
        return None

    voucher.status = not bool(voucher.status)
    db.session.commit()
    return voucher


def get_order_for_restaurant(user_id, order_id):
    restaurant = get_restaurant_by_user_id(user_id)
    if not restaurant:
        return None, None

    try:
        order = (
            Order.query.filter_by(order_id=int(order_id), restaurant_id=restaurant.restaurant_id)
            .options(
                selectinload(Order.items).selectinload(OrderItem.dish),
                selectinload(Order.customer).selectinload(Customer.user),
                selectinload(Order.payment),
                selectinload(Order.voucher),
            )
            .one_or_none()
        )
    except (TypeError, ValueError):
        order = None

    return restaurant, order


def confirm_order_for_restaurant(user_id, order_id):
    restaurant, order = get_order_for_restaurant(user_id, order_id)
    if not restaurant or not order:
        return None, "not_found"

    current_status = (order.status or "").strip().lower()
    if current_status in {"cancelled", "canceled"}:
        return order, "cancelled"
    if current_status in {"refund_pending", "pending_refund"}:
        return order, "refund_pending"
    if current_status in {"completed", "delivered", "done"}:
        return order, "completed"

    order.status = "preparing"
    db.session.commit()
    return order, "confirmed"


def _clear_cancel_request_fields(order):
    order.cancel_request_status = None
    order.cancel_request_reason = None
    order.cancel_request_date = None
    order.cancel_request_handled_at = None
    order.cancel_request_handled_by = None
    order.cancel_request_admin_note = None


def _mark_cancel_request_pending(order, reason=""):
    resolved_reason = _clean(reason)
    order.cancel_request_status = "pending"
    order.cancel_request_reason = resolved_reason or "Nhà hàng đề nghị hủy đơn."
    order.cancel_request_date = vietnam_now()
    order.cancel_request_handled_at = None
    order.cancel_request_handled_by = None
    order.cancel_request_admin_note = None
    return order.cancel_request_reason


def _apply_order_cancellation(order, reason="", handled_by=None, admin_note=""):
    resolved_reason = _clean(reason)
    payment_method = (order.payment.payment_method if order.payment else "").strip().lower()
    payment_status = (order.payment.status if order.payment else "").strip().lower()

    if payment_method == "momo" and payment_status == "paid":
        order.status = "refund_pending"
        next_status = "refund_pending"
    else:
        order.status = "cancelled"
        next_status = "cancelled"
        if order.payment and payment_status != "paid":
            order.payment.status = "cancelled"

    order.cancel_reason = resolved_reason or order.cancel_reason or "Không có lý do cụ thể."
    order.cancel_request_status = "approved"
    order.cancel_request_reason = resolved_reason or order.cancel_request_reason
    order.cancel_request_date = order.cancel_request_date or vietnam_now()
    order.cancel_request_handled_at = vietnam_now()
    order.cancel_request_handled_by = handled_by
    order.cancel_request_admin_note = _clean(admin_note) or None
    return next_status, resolved_reason


def complete_order_for_restaurant(user_id, order_id):
    restaurant, order = get_order_for_restaurant(user_id, order_id)
    if not restaurant or not order:
        return None, "not_found"

    current_status = (order.status or "").strip().lower()
    if current_status in {"cancelled", "canceled"}:
        return order, "cancelled"
    if current_status in {"refund_pending", "pending_refund"}:
        return order, "refund_pending"
    if current_status in {"completed", "delivered", "done"}:
        return order, "completed"
    if _clean(getattr(order, "cancel_request_status", "")).lower() == "pending":
        return order, "cancel_request_pending"
    if current_status not in {"preparing"}:
        return order, current_status or "invalid"

    order.status = "shipping"
    order.shipping_at = vietnam_now()
    db.session.commit()
    return order, "shipping"


def cancel_order_for_restaurant(user_id, order_id, reason=""):
    restaurant, order = get_order_for_restaurant(user_id, order_id)
    if not restaurant or not order:
        return None, "not_found", ""

    current_status = (order.status or "").strip().lower()
    if current_status in {"cancelled", "canceled"}:
        return order, "already_cancelled", _clean(reason)
    if current_status in {"refund_pending", "pending_refund"}:
        return order, "already_refund_pending", _clean(reason)
    if _clean(getattr(order, "cancel_request_status", "")).lower() == "pending":
        return order, "cancel_request_pending", _clean(reason)

    resolved_reason = _clean(reason)
    next_status, _ = _apply_order_cancellation(order, reason=resolved_reason)
    _clear_cancel_request_fields(order)
    db.session.commit()
    return order, next_status, resolved_reason


def request_cancel_order_for_restaurant(user_id, order_id, reason=""):
    restaurant, order = get_order_for_restaurant(user_id, order_id)
    if not restaurant or not order:
        return None, "not_found", ""

    current_status = (order.status or "").strip().lower()
    if current_status in {"cancelled", "canceled"}:
        return order, "already_cancelled", _clean(reason)
    if current_status in {"refund_pending", "pending_refund"}:
        return order, "already_refund_pending", _clean(reason)
    if current_status in {"completed", "delivered", "done"}:
        return order, "already_completed", _clean(reason)
    if current_status != "preparing":
        return order, current_status or "invalid", _clean(reason)
    if _clean(getattr(order, "cancel_request_status", "")).lower() == "pending":
        return order, "already_requested", _clean(reason)

    resolved_reason = _mark_cancel_request_pending(order, reason=reason)
    db.session.commit()

    if restaurant.user:
        restaurant_name = restaurant.user.display_name or restaurant.user.username or "Nhà hàng"
    else:
        restaurant_name = "Nhà hàng"
    admin_ids = [user.user_id for user in User.query.filter_by(role="admin").all()]
    emit_structured_notifications_to_users(
        build_restaurant_cancel_request_notification(order, restaurant_name=restaurant_name, reason=resolved_reason),
        admin_ids,
    )
    if order.customer_id:
        emit_structured_notification(
            {
                "user_id": order.customer_id,
                "type": "customer_order_cancel_request",
                "title": f"Nhà hàng gửi yêu cầu hủy đơn #{order.order_id}",
                "message": f"{restaurant_name} đã gửi yêu cầu hủy đơn và đang chờ admin duyệt.",
                "link": url_for("auth.order_detail", order_id=order.order_id),
                "payload": {
                    "order_id": order.order_id,
                    "restaurant_name": restaurant_name,
                    "request_reason": resolved_reason,
                },
            }
        )

    return order, "requested", resolved_reason


def withdraw_cancel_request_for_restaurant(user_id, order_id):
    restaurant, order = get_order_for_restaurant(user_id, order_id)
    if not restaurant or not order:
        return None, "not_found"

    if _clean(getattr(order, "cancel_request_status", "")).lower() != "pending":
        return order, "no_pending_request"

    order.cancel_request_status = None
    order.cancel_request_reason = None
    order.cancel_request_date = None
    order.cancel_request_handled_at = None
    order.cancel_request_handled_by = None
    order.cancel_request_admin_note = None
    db.session.commit()

    if restaurant.user:
        restaurant_name = restaurant.user.display_name or restaurant.user.username or "Nhà hàng"
    else:
        restaurant_name = "Nhà hàng"
    admin_ids = [user.user_id for user in User.query.filter_by(role="admin").all()]
    emit_structured_notifications_to_users(
        {
            "type": "admin_order_cancel_request_withdrawn",
            "title": f"Đã rút yêu cầu hủy đơn #{order.order_id}",
            "message": f"{restaurant_name} vừa rút yêu cầu hủy đơn.",
            "link": url_for("admin.disputes"),
            "payload": {
                "order_id": order.order_id,
                "restaurant_name": restaurant_name,
            },
        },
        admin_ids,
    )
    if order.customer_id:
        emit_structured_notification(
            {
                "user_id": order.customer_id,
                "type": "customer_order_cancel_request_withdrawn",
                "title": f"Nhà hàng đã rút yêu cầu hủy đơn #{order.order_id}",
                "message": f"{restaurant_name} đã hủy bỏ yêu cầu hủy đơn trước đó.",
                "link": url_for("auth.order_detail", order_id=order.order_id),
                "payload": {
                    "order_id": order.order_id,
                    "restaurant_name": restaurant_name,
                },
            }
        )

    return order, "withdrawn"


def process_cancel_request_for_admin(order_id, approved, admin_user_id, admin_note=""):
    try:
        order = (
            Order.query.options(
                selectinload(Order.customer).selectinload(Customer.user),
                selectinload(Order.restaurant).selectinload(Restaurant.user),
                selectinload(Order.payment),
                selectinload(Order.voucher),
            )
            .filter_by(order_id=int(order_id))
            .one_or_none()
        )
    except (TypeError, ValueError):
        order = None

    if not order:
        return None, "not_found", ""

    restaurant_name = order.restaurant.user.display_name if order.restaurant and order.restaurant.user else "Nhà hàng"
    request_reason = _clean(getattr(order, "cancel_request_reason", "") or "")
    current_request_status = _clean(getattr(order, "cancel_request_status", "")).lower()

    if current_request_status not in {"pending", "approved", "rejected"}:
        return order, "no_pending_request", ""

    if current_request_status in {"approved", "rejected"} and approved:
        return order, "already_processed", request_reason
    if current_request_status in {"approved", "rejected"} and not approved:
        return order, "already_processed", request_reason

    if not approved:
        order.cancel_request_status = "rejected"
        order.cancel_request_handled_at = vietnam_now()
        order.cancel_request_handled_by = admin_user_id
        order.cancel_request_admin_note = _clean(admin_note) or "Admin đã từ chối yêu cầu hủy."
        db.session.commit()

        emit_structured_notification(
            build_restaurant_cancel_request_result_notification(
                order,
                restaurant_name=restaurant_name,
                approved=False,
                admin_note=order.cancel_request_admin_note or "",
            )
        )
        if order.customer_id:
            emit_structured_notification(
                {
                    "user_id": order.customer_id,
                    "type": "customer_order_cancel_request_rejected",
                    "title": f"Yêu cầu hủy đơn #{order.order_id} bị từ chối",
                    "message": f"Admin đã từ chối yêu cầu hủy từ {restaurant_name}.",
                    "link": url_for("auth.order_detail", order_id=order.order_id),
                    "payload": {
                        "order_id": order.order_id,
                        "restaurant_name": restaurant_name,
                        "request_reason": request_reason,
                        "admin_note": order.cancel_request_admin_note or "",
                    },
                }
            )
        return order, "rejected", request_reason

    next_status, resolved_reason = _apply_order_cancellation(
        order,
        reason=request_reason,
        handled_by=admin_user_id,
        admin_note=admin_note,
    )
    db.session.commit()

    emit_structured_notification(
        build_restaurant_cancel_request_result_notification(
            order,
            restaurant_name=restaurant_name,
            approved=True,
            admin_note=admin_note,
        )
    )
    emit_structured_notification(
        build_order_cancelled_notification(
            order,
            cancel_reason=resolved_reason,
            restaurant_name=restaurant_name,
        )
    )
    return order, next_status, resolved_reason


def delete_voucher_for_restaurant(user_id, voucher_id):
    restaurant, voucher = get_voucher_for_restaurant(user_id, voucher_id)
    if not restaurant or not voucher:
        return False

    if voucher.orders:
        return False

    db.session.delete(voucher)
    db.session.commit()
    return True


def delete_dish_for_restaurant(user_id, dish_id):
    restaurant, dish = get_dish_for_restaurant(user_id, dish_id)
    if not restaurant or not dish:
        return False

    db.session.delete(dish)
    db.session.commit()
    return True


def report_review_for_restaurant(user_id, review_id, reason=""):
    restaurant = get_restaurant_by_user_id(user_id)
    if not restaurant:
        return None, "restaurant_not_found"

    review = db.session.get(Review, int(review_id))
    if not review or review.restaurant_id != restaurant.restaurant_id:
        return None, "review_not_found"

    if _clean(review.report_status).lower() == "pending":
        return review, "already_reported"

    review.report_status = "pending"
    review.report_reason = _clean(reason) or "Đánh giá bị cho là không đúng sự thật."
    review.report_date = datetime.utcnow()
    review.report_admin_action = None
    review.report_admin_note = None
    review.report_handled_at = None
    review.report_handled_by = None
    db.session.commit()

    admin_ids = [user.user_id for user in User.query.filter_by(role="admin").all()]
    emit_structured_notifications_to_users(
        build_restaurant_review_report_notification(
            review,
            restaurant_name=restaurant.user.display_name if restaurant.user else "Nhà hàng",
            reason=review.report_reason or "",
        ),
        admin_ids,
    )
    return review, "reported"
