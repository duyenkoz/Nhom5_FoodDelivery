import os
import re

from flask import current_app
import bcrypt
from werkzeug.utils import secure_filename
from sqlalchemy import func

from app.extensions import db
from app.models.customer import Customer
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.location_service import normalize_text, resolve_address_for_area


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,30}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_PATTERN = re.compile(r"^(03|05|07|08|09)[0-9]{8}$")
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 72
CUSTOMER_AREAS = {"Hồ Chí Minh", "Hà Nội", "Đà Nẵng"}
RESTAURANT_AREAS = {"Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "Cần Thơ"}


def normalize_role(role_raw):
    return "customer" if role_raw == "KHACHHANG" else "restaurant"


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _resolve_profile_location(address, area, allowed_areas):
    if area not in allowed_areas:
        return None, {"khuVuc": "Vui lòng chọn khu vực hợp lệ."}

    location = resolve_address_for_area(address, area)
    if not location:
        return None, {"diaChi": "Địa chỉ phải khớp với khu vực đã chọn."}

    return location, {}


def _selected_area_aliases(area):
    normalized = normalize_text(area)
    aliases = {
        "hồ chí minh": ("hồ chí minh", "thành phố hồ chí minh", "tp hcm", "tphcm", "hcm"),
        "hà nội": ("hà nội", "thành phố hà nội", "tp hà nội", "hanoi", "tphn"),
        "đà nẵng": ("đà nẵng", "thành phố đà nẵng", "tp đà nẵng", "danang", "tpdn"),
        "cần thơ": ("cần thơ", "thành phố cần thơ", "tp cần thơ", "cantho", "tpct"),
    }.get(normalized, (normalized,))
    return [normalize_text(alias) for alias in aliases if alias]


def _strip_city_tail(parts, area):
    cleaned = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    aliases = _selected_area_aliases(area)

    while cleaned:
        tail = normalize_text(cleaned[-1])
        if any(alias and alias in tail for alias in aliases) or "thanh pho" in tail:
            cleaned.pop()
            continue
        break

    return cleaned


def _compact_address_from_components(address_components):
    if isinstance(address_components, dict):
        ordered_keys = [
            "house_number",
            "road",
            "pedestrian",
            "neighbourhood",
            "neighborhood",
            "suburb",
            "quarter",
            "city_district",
            "county",
            "district",
            "borough",
            "municipality",
        ]
        parts = []
        for key in ordered_keys:
            value = address_components.get(key)
            if value and value not in parts:
                parts.append(value)
        return parts

    if isinstance(address_components, list):
        type_to_bucket = [
            ("street_number",),
            ("route",),
            ("premise",),
            ("subpremise",),
            ("neighborhood", "neighbourhood"),
            ("sublocality_level_1",),
            ("sublocality_level_2",),
            ("locality",),
            ("administrative_area_level_2",),
            ("city_district",),
            ("county",),
        ]
        parts = []
        used_values = set()
        for bucket in type_to_bucket:
            for component in address_components:
                if not isinstance(component, dict):
                    continue
                types = component.get("types") or []
                if not any(type_name in types for type_name in bucket):
                    continue
                value = component.get("long_name") or component.get("short_name") or ""
                value = value.strip()
                if value and value not in used_values:
                    parts.append(value)
                    used_values.add(value)
                    break
        return parts

    return []


def _shorten_restaurant_address(location, area):
    raw_parts = _compact_address_from_components(location.get("address_components"))
    if not raw_parts:
        raw_text = location.get("formatted_address") or location.get("display_name") or location.get("address") or ""
        raw_parts = [part.strip() for part in raw_text.split(",") if part.strip()]

    compacted = _strip_city_tail(raw_parts, area)
    if compacted:
        return ", ".join(compacted)

    return _clean(location.get("display_name") or location.get("address") or "")


def hash_password(raw_password):
    password = raw_password or ""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(stored_password, raw_password):
    if not stored_password:
        return False

    candidate = raw_password or ""
    stored_value = stored_password.strip()

    if stored_value.startswith("$2a$") or stored_value.startswith("$2b$") or stored_value.startswith("$2y$"):
        try:
            return bcrypt.checkpw(candidate.encode("utf-8"), stored_value.encode("utf-8"))
        except ValueError:
            return False

    return stored_value == candidate


def set_user_password(user, raw_password):
    user.password = hash_password(raw_password)
    return user


def _validate_customer_profile(form):
    display_name = _clean(form.get("tenHienThi"))
    address = _clean(form.get("diaChi"))
    area = _clean(form.get("khuVuc"))
    errors = {}

    if not display_name:
        errors["tenHienThi"] = "Vui lòng nhập tên hiển thị."
    elif len(display_name) > 100:
        errors["tenHienThi"] = "Tên hiển thị không được vượt quá 100 ký tự."

    if not address:
        errors["diaChi"] = "Vui lòng nhập địa chỉ."
    elif len(address) > 200:
        errors["diaChi"] = "Địa chỉ không được vượt quá 200 ký tự."

    if area not in CUSTOMER_AREAS:
        errors["khuVuc"] = "Vui lòng chọn khu vực hợp lệ."

    location = None
    if address and area:
        location, location_errors = _resolve_profile_location(address, area, CUSTOMER_AREAS)
        errors.update(location_errors)

    if errors:
        raise ValueError(errors)

    return {
        "tenHienThi": display_name,
        "diaChi": address,
        "khuVuc": area,
        "latitude": location["lat"] if location else None,
        "longitude": location["lon"] if location else None,
    }


def _validate_restaurant_profile(form, file_storage=None):
    display_name = _clean(form.get("tenNhaHang"))
    address = _clean(form.get("diaChi"))
    area = _clean(form.get("khuVuc"))
    description = _clean(form.get("moTa"))
    errors = {}

    if not display_name:
        errors["tenNhaHang"] = "Vui lòng nhập tên nhà hàng."
    elif len(display_name) > 100:
        errors["tenNhaHang"] = "Tên nhà hàng không được vượt quá 100 ký tự."

    if not address:
        errors["diaChi"] = "Vui lòng nhập địa chỉ."
    elif len(address) > 200:
        errors["diaChi"] = "Địa chỉ không được vượt quá 200 ký tự."

    if area not in RESTAURANT_AREAS:
        errors["khuVuc"] = "Vui lòng chọn khu vực hợp lệ."

    location = None
    if address and area:
        location, location_errors = _resolve_profile_location(address, area, RESTAURANT_AREAS)
        errors.update(location_errors)

    if description and len(description) > 500:
        errors["moTa"] = "Mô tả không được vượt quá 500 ký tự."

    if file_storage and file_storage.filename:
        filename = file_storage.filename.strip()
        if "." not in filename:
            errors["anhNhaHang"] = "Vui lòng chọn ảnh hợp lệ."
        else:
            ext = filename.rsplit(".", 1)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                errors["anhNhaHang"] = "Ảnh phải có định dạng jpg, jpeg, png, gif hoặc webp."

    if errors:
        raise ValueError(errors)

    return {
        "tenNhaHang": display_name,
        "diaChi": _shorten_restaurant_address(location, area) if location else address,
        "khuVuc": area,
        "moTa": description,
        "latitude": location["lat"] if location else None,
        "longitude": location["lon"] if location else None,
    }


def _validate_registration(form):
    username = _clean(form.get("username"))
    email = _clean(form.get("email"))
    phone = _clean(form.get("phone"))
    password = form.get("password") or ""
    password_confirm = form.get("password_confirm") or ""
    role_raw = form.get("role")

    errors = {}

    if not username:
        errors["username"] = "Vui lòng nhập tên đăng nhập."
    elif not USERNAME_PATTERN.fullmatch(username):
        errors["username"] = "Tên đăng nhập chỉ gồm chữ, số, dấu gạch dưới và dài 3-30 ký tự."
    elif username_exists(username):
        errors["username"] = "Tên đăng nhập đã tồn tại."

    if not email:
        errors["email"] = "Vui lòng nhập email."
    elif not EMAIL_PATTERN.fullmatch(email):
        errors["email"] = "Email không hợp lệ."
    elif User.query.filter(func.lower(User.email) == email.lower()).first() is not None:
        errors["email"] = "Email đã được sử dụng."

    if not phone:
        errors["phone"] = "Vui lòng nhập số điện thoại."
    elif not PHONE_PATTERN.fullmatch(phone):
        errors["phone"] = "Số điện thoại phải bắt đầu bằng 03, 05, 07, 08 hoặc 09 và có 10 số."

    if not password:
        errors["password"] = "Vui lòng nhập mật khẩu."
    elif len(password) < PASSWORD_MIN_LENGTH:
        errors["password"] = f"Mật khẩu phải có ít nhất {PASSWORD_MIN_LENGTH} ký tự."
    elif len(password) > PASSWORD_MAX_LENGTH:
        errors["password"] = "Mật khẩu quá dài."

    if password_confirm != password:
        errors["password_confirm"] = "Mật khẩu nhập lại không khớp."

    if role_raw not in {"KHACHHANG", "NHAHANG"}:
        errors["role"] = "Vui lòng chọn vai trò hợp lệ."

    if errors:
        raise ValueError(errors)

    return {
        "username": username,
        "email": email,
        "phone": phone,
        "password": password,
        "role": role_raw,
    }


def create_registration_user(form):
    data = _validate_registration(form)
    user = User(
        username=data["username"],
        email=data["email"],
        phone=data["phone"],
        password=hash_password(data["password"]),
        role=normalize_role(data["role"]),
        status=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def get_user_by_id(user_id):
    if not user_id:
        return None
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def is_customer_profile_complete(user_id):
    user = get_user_by_id(user_id)
    if not user or user.role != "customer":
        return False

    customer = db.session.get(Customer, user.user_id)
    if not customer:
        return False

    return bool(customer.address and customer.area)


def is_restaurant_profile_complete(user_id):
    user = get_user_by_id(user_id)
    if not user or user.role != "restaurant":
        return False

    restaurant = db.session.get(Restaurant, user.user_id)
    if not restaurant:
        return False

    return bool(restaurant.address and restaurant.area)

def get_restaurant_by_user_id(user_id):
    user = get_user_by_id(user_id)
    if not user:
        return None, None

    restaurant = Restaurant.query.filter_by(restaurant_id=user.user_id).one_or_none()
    return user, restaurant


def complete_customer_profile(user_id, form):
    user = get_user_by_id(user_id)
    if not user:
        return None

    data = _validate_customer_profile(form)
    user.display_name = data["tenHienThi"]
    customer = db.session.get(Customer, user.user_id)
    if not customer:
        customer = Customer(customer_id=user.user_id)
        db.session.add(customer)

    customer.address = data["diaChi"]
    customer.area = data["khuVuc"]
    customer.latitude = data["latitude"]
    customer.longitude = data["longitude"]
    db.session.commit()
    return user


def complete_restaurant_profile(user_id, form, file_storage=None):
    user, restaurant = get_restaurant_by_user_id(user_id)
    if not user:
        return None

    data = _validate_restaurant_profile(form, file_storage)
    user.display_name = data["tenNhaHang"]

    filename = ""
    if file_storage and file_storage.filename:
        filename = secure_filename(file_storage.filename)
        upload_dir = os.path.join(current_app.static_folder, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        file_storage.save(os.path.join(upload_dir, filename))
        filename = f"uploads/{filename}"

    restaurant = db.session.get(Restaurant, user.user_id)
    if not restaurant:
        restaurant = Restaurant(restaurant_id=user.user_id, platform_fee=0)
        db.session.add(restaurant)

    if filename:
        restaurant.image = filename
    restaurant.platform_fee = restaurant.platform_fee or 0
    restaurant.address = data["diaChi"]
    restaurant.area = data["khuVuc"]
    restaurant.latitude = data["latitude"]
    restaurant.longitude = data["longitude"]
    restaurant.description = data["moTa"]
    db.session.commit()
    return user


def username_exists(username):
    if not username:
        return False
    return User.query.filter_by(username=username).first() is not None
