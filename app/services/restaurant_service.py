import os
import re
from datetime import date, datetime

from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.customer import Customer
from app.models.dish import Dish
from app.models.order import Order
from app.models.review import Review
from app.models.user import User
from app.models.voucher import Voucher
from app.models.restaurant import Restaurant


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
    "amount": "Giảm tiền",
    "percent": "Giảm %",
}


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


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


def build_dish_view_model(dish, index=0):
    category = dish.category or infer_category(dish)
    dish_id = dish.dish_id or 0
    price = dish.price or 0
    today_orders = max(8, (price // 1000) % 60 + 8 + index * 2)
    avg_day_orders = max(6, (price // 1200) % 55 + 6)
    rating_value = round(4.0 + ((dish_id % 8) * 0.1), 1)
    rating_count = 20 + (dish_id % 180)
    image_path = dish.image or infer_image_path(category, dish)

    return {
        "dish": dish,
        "category": category,
        "image_path": image_path,
        "today_orders": today_orders,
        "avg_day_orders": avg_day_orders,
        "rating_value": rating_value,
        "rating_count": rating_count,
        "has_reviews": rating_count > 0,
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
    return value.strftime("%d/%m/%Y") if value else "Áp dụng ngay"


def _format_end_date_label(value):
    return value.strftime("%d/%m/%Y") if value else "Không giới hạn"


def _voucher_discount_text(voucher):
    discount_label = VOUCHER_DISCOUNT_LABELS.get(voucher.discount_type or "", "Giảm")
    if voucher.discount_type == "percent":
        value = f"{voucher.discount_value or 0}%"
    else:
        value = f"{'{:,}'.format(voucher.discount_value or 0)}đ"
    return f"{discount_label}: {value}"


def _voucher_state_info(voucher):
    today = date.today()
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
    discount_type = _clean(form.get("discount_type"))
    discount_value_raw = _clean(form.get("discount_value"))
    start_date_raw = _clean(form.get("start_date"))
    end_date_raw = _clean(form.get("end_date"))
    errors = {}

    if not voucher_code:
        errors["voucher_code"] = "Vui lòng nhập mã voucher."
    elif len(voucher_code) > 50:
        errors["voucher_code"] = "Mã voucher không được vượt quá 50 ký tự."

    if discount_type not in {"amount", "percent"}:
        errors["discount_type"] = "Vui lòng chọn kiểu giảm giá."

    if not discount_value_raw:
        errors["discount_value"] = "Vui lòng nhập giá trị giảm giá."
    else:
        try:
            discount_value = int(discount_value_raw)
            if discount_value <= 0:
                raise ValueError
            if discount_type == "percent" and discount_value > 100:
                raise ValueError
        except ValueError:
            errors["discount_value"] = (
                "Giảm theo % phải từ 1 đến 100."
                if discount_type == "percent"
                else "Giá trị giảm phải là số nguyên lớn hơn 0."
            )

    start_date = None
    end_date = None
    try:
        start_date = _parse_date_input(start_date_raw) if start_date_raw else date.today()
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
        "discount_type": discount_type,
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
    per_page=6,
):
    restaurant = get_restaurant_by_user_id(user_id)
    dishes = list(restaurant.dishes) if restaurant else []
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

    dish_views = [build_dish_view_model(dish, index) for index, dish in enumerate(dishes)]
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

    stats = {
        "total": len(dish_views),
        "active": sum(1 for item in dish_views if item["dish"].status),
        "inactive": sum(1 for item in dish_views if not item["dish"].status),
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
        },
    }


def _safe_user_name(user):
    if not user:
        return "Khách ẩn danh"
    return user.display_name or user.username or "Khách ẩn danh"


def build_voucher_section_context(
    user_id,
    edit_voucher_id=None,
    form_values=None,
    form_errors=None,
    query="",
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

    edit_voucher = None
    if edit_voucher_id is not None:
        _, edit_voucher = get_voucher_for_restaurant(user_id, edit_voucher_id)

    if form_values is None:
        if edit_voucher:
            form_values = {
                "voucher_id": edit_voucher.voucher_id,
                "voucher_code": edit_voucher.voucher_code or "",
                "discount_type": edit_voucher.discount_type or "amount",
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
                "start_date": date.today().isoformat(),
                "end_date": "",
                "status": "on",
                "voucher_scope": "restaurant",
            }

    if not _clean((form_values or {}).get("start_date")):
        form_values = dict(form_values or {})
        form_values["start_date"] = date.today().isoformat()

    today = date.today()
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
        "items": voucher_views,
        "stats": stats,
        "edit_voucher": edit_voucher,
        "form_values": form_values,
        "form_errors": form_errors or {},
        "search_query": query,
    }


def build_section_context(user_id, section_name, edit_voucher_id=None, form_values=None, form_errors=None, query=""):
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
            "items": items,
            "stats": stats,
        }

    if section_name == "orders":
        orders = (
            Order.query.filter_by(restaurant_id=restaurant.restaurant_id)
            .order_by(Order.order_date.desc())
            .all()
        )
        items = []
        for order in orders:
            items.append(
                {
                    "order": order,
                    "customer_name": _safe_user_name(order.customer.user) if order.customer and order.customer.user else "Khách ẩn danh",
                }
            )
        stats = {
            "total_orders": len(items),
            "completed_orders": sum(1 for item in items if (item["order"].status or "").lower() in {"completed", "delivered", "done"}),
        }
        return {
            "restaurant": restaurant,
            "section_name": section_name,
            "section_title": "Quản lý đơn hàng",
            "section_subtitle": "Theo dõi các đơn hàng mới nhất của nhà hàng.",
            "items": items,
            "stats": stats,
        }

    if section_name == "vouchers":
        return build_voucher_section_context(
            user_id,
            edit_voucher_id=edit_voucher_id,
            form_values=form_values,
            form_errors=form_errors,
            query=query,
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
        voucher = Voucher(created_by=restaurant.restaurant_id, voucher_scope="restaurant")
        db.session.add(voucher)
        duplicate = (
            Voucher.query.filter(db.func.upper(Voucher.voucher_code) == data["voucher_code"]).first()
        )

    if duplicate:
        raise ValueError({"voucher_code": "Mã voucher đã tồn tại."})

    voucher.voucher_code = data["voucher_code"]
    voucher.discount_type = data["discount_type"]
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
    return review, "reported"
