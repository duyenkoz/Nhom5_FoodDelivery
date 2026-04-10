from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from app.models.user import User
from app.services.auth_service import (
    complete_customer_profile,
    complete_restaurant_profile,
    create_registration_user,
    USERNAME_PATTERN,
    username_exists,
    verify_password,
)
from app.services.password_reset_service_fixed import RESEND_COOLDOWN_SECONDS

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


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
                session.permanent = remember
                if user.role == "restaurant":
                    return redirect(url_for("auth.restaurant_dashboard"))
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


@bp.route("/restaurant/dashboard")
def restaurant_dashboard():
    return render_template(
        "partials/restaurant.html",
        show_search=False,
        show_auth=False,
    )


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


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home.index"))


@bp.route("/complete-customer", methods=["GET", "POST"])
def complete_customer():
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
    if request.method == "POST":
        try:
            user = complete_restaurant_profile(
                session.get("user_id"),
                request.form,
                request.files.get("anhNhaHang"),
            )
        except ValueError as exc:
            form_errors = exc.args[0] if exc.args else {}
            return render_template(
                "auth/complete_restaurant.html",
                form_errors=form_errors,
                form_values=request.form,
                show_search=False,
                show_auth=False,
            )
        if not user:
            return redirect(url_for("auth.register"))
        return redirect(url_for("home.index"))

    return render_template("auth/complete_restaurant.html", show_search=False, show_auth=False)


@bp.route("/check-username")
def check_username():
    return jsonify({"exists": username_exists(request.args.get("username"))})
