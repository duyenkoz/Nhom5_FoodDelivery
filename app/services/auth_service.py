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
from app.services.location_service import resolve_address_for_area


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
        "diaChi": address,
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
    user = get_user_by_id(user_id)
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

    restaurant = db.session.get(Restaurant, user.user_id)
    if not restaurant:
        restaurant = Restaurant(restaurant_id=user.user_id, platform_fee=0)
        db.session.add(restaurant)

    restaurant.image = filename or restaurant.image
    restaurant.address = data["diaChi"]
    restaurant.area = data["khuVuc"]
    restaurant.latitude = data["latitude"]
    restaurant.longitude = data["longitude"]
    restaurant.description = data["moTa"]
    restaurant.platform_fee = restaurant.platform_fee or 0
    db.session.commit()
    return user


def username_exists(username):
    if not username:
        return False
    return User.query.filter_by(username=username).first() is not None
