from sqlalchemy import or_
from sqlalchemy import cast, String
from sqlalchemy.orm import selectinload

from app.models.order import Order
from app.models.review import Review
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.voucher import Voucher
from app.services.shipping_service import build_shipping_rules_form_values, get_shipping_fee_settings
from app.utils.time_utils import format_vietnam_date, format_vietnam_datetime


ROLE_OPTIONS = ("all", "customer", "restaurant", "admin")
ROLE_LABELS = {
    "all": "Tất cả",
    "customer": "Khách hàng",
    "restaurant": "Nhà hàng",
    "admin": "Quản trị viên",
}


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _safe_name(user):
    if not user:
        return "Chưa rõ"
    return (user.display_name or user.username or "Chưa rõ").strip()


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
    return "{:,}đ".format(max(0, int(value or 0)))


def _paginate(items, page=1, per_page=10):
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
        "items": items[start:end],
    }


def _build_account_item(user):
    customer_profile = getattr(user, "customer_profile", None)
    restaurant_profile = getattr(user, "restaurant_profile", None)
    role_label = ROLE_LABELS.get(user.role, "Khác")
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
        "records": _paginate(items, page=page, per_page=per_page),
        "stats": stats,
        "role_filter": normalized_role,
        "search_query": query,
        "section_title": "Quản lý tài khoản",
        "section_subtitle": "Xem và kiểm soát tài khoản khách hàng, nhà hàng và quản trị.",
    }


def _build_voucher_item(voucher):
    creator = voucher.creator
    creator_role = ROLE_LABELS.get(creator.role, "T?i kho?n") if creator else "T?i kho?n"
    discount_text = "{:,}?".format(voucher.discount_value or 0)
    status_text = "?ang b?t" if voucher.status else "?ang t?t"
    usage_count = len(voucher.orders or [])
    return {
        "voucher": voucher,
        "code": voucher.voucher_code or "",
        "creator_name": _safe_name(creator),
        "creator_role": creator_role,
        "discount_text": discount_text,
        "scope_text": "H? th?ng" if voucher.voucher_scope == "system" else "Nh? h?ng",
        "status_text": status_text,
        "usage_count": usage_count,
        "start_date": format_vietnam_date(voucher.start_date) if voucher.start_date else "?p d?ng ngay",
        "end_date": format_vietnam_date(voucher.end_date) if voucher.end_date else "Kh?ng gi?i h?n",
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
        "records": _paginate(items, page=page, per_page=per_page),
        "stats": stats,
        "search_query": query,
        "section_title": "Quản lý voucher",
        "section_subtitle": "Theo dõi toàn bộ voucher hệ thống và voucher của nhà hàng.",
    }


def _build_review_item(review):
    restaurant_name = _safe_name(review.restaurant.user) if review.restaurant and review.restaurant.user else "Chưa rõ"
    customer_name = _safe_name(review.customer.user) if review.customer and review.customer.user else "Khách ẩn danh"
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
        "records": _paginate(items, page=page, per_page=per_page),
        "stats": stats,
        "search_query": query,
        "section_title": "Quản lý đánh giá",
        "section_subtitle": "Duyệt nhanh các đánh giá gần đây từ khách hàng.",
    }


def _build_report_item(review):
    item = _build_review_item(review)
    item["severity"] = "Cao" if (review.rating or 0) <= 2 else "Trung bình"
    item["report_note"] = item["report_reason"] or "Nhà hàng báo cáo đánh giá này có dấu hiệu không chính xác."
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
        "records": _paginate(items, page=page, per_page=per_page),
        "stats": stats,
        "search_query": query,
        "section_title": "Báo cáo đánh giá",
        "section_subtitle": "Các đánh giá bị nhà hàng báo cáo cần admin xem xét.",
    }


def _build_complaint_item(review):
    restaurant_name = _safe_name(review.restaurant.user) if review.restaurant and review.restaurant.user else "Chưa rõ"
    customer_name = _safe_name(review.customer.user) if review.customer and review.customer.user else "Khách ẩn danh"
    return {
        "review": review,
        "restaurant_name": restaurant_name,
        "customer_name": customer_name,
        "created_at": _format_datetime(review.review_date),
        "severity": "Cao" if (review.rating or 0) <= 1 else "Trung bình",
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
        "records": _paginate(items, page=page, per_page=per_page),
        "stats": stats,
        "search_query": query,
        "section_title": "Khiếu nại",
        "section_subtitle": "Các phản hồi tiêu cực cần theo dõi và xử lý sớm.",
    }


def _build_dispute_item(order):
    customer_name = _safe_name(order.customer.user) if order.customer and order.customer.user else "Khách ẩn danh"
    restaurant_name = _safe_name(order.restaurant.user) if order.restaurant and order.restaurant.user else "Chưa rõ"
    return {
        "order": order,
        "customer_name": customer_name,
        "restaurant_name": restaurant_name,
        "created_at": _format_datetime(order.order_date),
        "status_label": order.status or "unknown",
    }


def _build_disputes(query="", page=1, per_page=10):
    dispute_status_keywords = {"cancel", "canceled", "cancelled", "dispute", "complaint", "refund"}
    orders = Order.query.order_by(Order.order_date.desc()).all()
    items = []
    for order in orders:
        status_text = _clean(order.status).lower()
        if not status_text:
            continue
        if any(keyword in status_text for keyword in dispute_status_keywords):
            item = _build_dispute_item(order)
            if _match_query(order.delivery_address, order.status, item["customer_name"], item["restaurant_name"], query=query):
                items.append(item)

    stats = {
        "total": len(items),
        "cancelled": sum(1 for item in items if "cancel" in _clean(item["status_label"]).lower()),
        "disputed": sum(1 for item in items if "dispute" in _clean(item["status_label"]).lower()),
    }
    return {
        "records": _paginate(items, page=page, per_page=per_page),
        "stats": stats,
        "search_query": query,
        "section_title": "Hỗ trợ tranh chấp / hủy đơn",
        "section_subtitle": "Theo dõi các đơn có trạng thái hủy, tranh chấp hoặc cần hỗ trợ.",
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
        "records": _paginate(items, page=page, per_page=per_page),
        "stats": {
            "total": len(items),
            "configured": configured_count,
            "unconfigured": max(0, len(items) - configured_count),
            "average_fee": average_fee,
        },
        "area_options": area_options,
        "search_query": query,
        "section_title": "Phí sàn nhà hàng",
        "section_subtitle": "Chỉnh phí sàn riêng cho từng nhà hàng. Checkout sẽ dùng đúng mức phí của nhà hàng đang thanh toán.",
    }


def build_admin_context(section_name="dashboard", query="", role_filter="all", page=1, per_page=10):
    section_name = section_name or "dashboard"
    pending_review_reports = Review.query.filter(Review.report_status == "pending").count()
    dashboard_stats = {
        "users": User.query.count(),
        "customers": User.query.filter_by(role="customer").count(),
        "restaurants": User.query.filter_by(role="restaurant").count(),
        "admins": User.query.filter_by(role="admin").count(),
        "vouchers": Voucher.query.count(),
        "reviews": Review.query.count(),
        "orders": Order.query.count(),
        "pending_cases": Review.query.filter((Review.rating <= 2) | (Review.sentiment.ilike("negative"))).count() + pending_review_reports,
        "pending_review_reports": pending_review_reports,
    }

    if section_name == "accounts":
        context = _build_accounts(role_filter=role_filter, query=query, page=page, per_page=per_page)
    elif section_name == "vouchers":
        context = _build_vouchers(query=query, page=page, per_page=per_page)
    elif section_name == "reviews":
        context = _build_reviews(query=query, page=page, per_page=per_page)
    elif section_name == "complaints":
        context = _build_complaints(query=query, page=page, per_page=per_page)
    elif section_name == "review_reports":
        context = _build_review_reports(query=query, page=page, per_page=per_page)
    elif section_name == "disputes":
        context = _build_disputes(query=query, page=page, per_page=per_page)
    elif section_name == "shipping":
        restaurant_fee_context = _build_restaurant_fees(query=query, page=page, per_page=per_page)
        context = {
            **restaurant_fee_context,
            "shipping_rules": build_shipping_rules_form_values(),
        }
    else:
        context = {
            "records": _paginate([], page=page, per_page=per_page),
            "stats": {},
            "search_query": query,
            "section_title": "Dashboard quản trị",
            "section_subtitle": "Tổng quan nhanh hệ thống, tài khoản và hoạt động gần đây.",
        }

    return {
        "section_name": section_name,
        "dashboard_stats": dashboard_stats,
        "role_filter": role_filter,
        **context,
    }
