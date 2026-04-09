from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from app.services.auth_service import (
    complete_customer_profile,
    complete_restaurant_profile,
    create_registration_user,
    username_exists,
)

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login")
def login():
    return render_template("auth/login.html", show_search=False, show_auth=False)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            new_user = create_registration_user(request.form)
        except ValueError as exc:
            form_errors = exc.args[0] if exc.args else {}
            return render_template(
                "auth/register.html",
                form_errors=form_errors,
                form_values=request.form,
            )
        session["user_id"] = new_user.user_id
        session["user_role"] = new_user.role

        if new_user.role == "customer":
            return redirect(url_for("auth.complete_customer"))
        return redirect(url_for("auth.complete_restaurant"))

    return render_template("auth/register.html")


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
            )
        if not user:
            return redirect(url_for("auth.register"))
        return redirect(url_for("home.index"))

    return render_template("auth/complete_customer.html")


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
            )
        if not user:
            return redirect(url_for("auth.register"))
        return redirect(url_for("home.index"))

    return render_template("auth/complete_restaurant.html")


@bp.route("/check-username")
def check_username():
    return jsonify({"exists": username_exists(request.args.get("username"))})
