from flask import Blueprint, jsonify, request

from app.services.password_reset_service_fixed import (
    resend_otp_for_email,
    request_otp_for_email,
    reset_password_for_email,
    verify_otp_logic,
)


bp = Blueprint("password_reset", __name__)


def _get_data():
    return request.get_json(silent=True) or request.form or {}


def _get_field(data, *names):
    for name in names:
        value = data.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, str):
            return value
    return ""


@bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = _get_data()
    email = _get_field(data, "email")
    payload, status_code = request_otp_for_email(email)
    return jsonify(payload), status_code


@bp.route("/verify-otp", methods=["POST"])
def verify_otp():
    data = _get_data()
    email = _get_field(data, "email")
    otp = _get_field(data, "otp")
    payload, status_code = verify_otp_logic(email, otp)
    return jsonify(payload), status_code


@bp.route("/resend-otp", methods=["POST"])
def resend_otp():
    data = _get_data()
    email = _get_field(data, "email")
    payload, status_code = resend_otp_for_email(email)
    return jsonify(payload), status_code


@bp.route("/reset-password", methods=["POST"])
def reset_password():
    data = _get_data()
    email = _get_field(data, "email")
    new_password = _get_field(data, "new_password", "password", "mat_khau_moi")
    confirm_password = _get_field(data, "confirm_password", "confirmPassword", "mat_khau_xac_nhan")
    payload, status_code = reset_password_for_email(email, new_password, confirm_password)
    return jsonify(payload), status_code
