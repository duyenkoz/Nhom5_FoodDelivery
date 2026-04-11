from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from flask import flash

from app.extensions import db
from app.models.user import User
from app.services.auth_service import (
    complete_customer_profile,
    complete_restaurant_profile,
    create_registration_user,
    is_customer_profile_complete,
    is_restaurant_profile_complete,
    get_restaurant_by_user_id,
    set_user_password,
    USERNAME_PATTERN,
    username_exists,
    verify_password,
)
from app.services.password_reset_service_fixed import RESEND_COOLDOWN_SECONDS

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _safe_next_url(next_url):
    if not next_url:
        return ""
    next_url = next_url.strip()
    if not next_url.startswith("/") or next_url.startswith("//"):
        return ""
    return next_url


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
            elif not verify_password(user.password, password):
                form_errors["password"] = "Mật khẩu không đúng. Vui lòng nhập lại."
            else:
                session["user_id"] = user.user_id
                session["user_role"] = user.role
                session["auth_state"] = "logged_in"
                session["username"] = user.username
                session["user_display_name"] = user.display_name or user.username
                session.permanent = remember
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
            show_search=False,
            show_auth=False,
        )

    return render_template(
        "auth/login.html",
        forgot_resend_cooldown=RESEND_COOLDOWN_SECONDS,
        show_search=False,
        show_auth=False,
    )


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
        session["user_id"] = new_user.user_id
        session["user_role"] = new_user.role

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

    session["user_id"] = user.user_id
    session["user_role"] = user.role
    session["auth_state"] = "logged_in"
    session["username"] = user.username
    session["user_display_name"] = user.display_name or user.username
    session.permanent = False
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


@bp.route("/account")
def account():
    if session.get("user_role") != "customer":
        return redirect(url_for("home.index"))

    return render_template(
        "auth/simple_page.html",
        page_title="Thông tin tài khoản",
        page_subtitle="Trang thông tin tài khoản đang được phát triển.",
        action_label="Về trang chủ",
        action_url=url_for("home.index"),
        show_search=False,
        show_auth=False,
    )


@bp.route("/orders")
def orders():
    if session.get("user_role") != "customer":
        return redirect(url_for("home.index"))

    return render_template(
        "auth/simple_page.html",
        page_title="Đơn hàng",
        page_subtitle="Trang đơn hàng đang được phát triển.",
        action_label="Về trang chủ",
        action_url=url_for("home.index"),
        show_search=False,
        show_auth=False,
    )


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
        return redirect(url_for("home.index"))

    return render_template("auth/complete_customer.html", show_search=False, show_auth=False)


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
        session["user_display_name"] = user.display_name or user.username
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
