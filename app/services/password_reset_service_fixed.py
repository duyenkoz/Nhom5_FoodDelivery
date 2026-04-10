import math
import secrets
import threading
import time

import bcrypt
from flask import current_app, session
from flask_mail import Message
from sqlalchemy import func

from app.extensions import db, mail
from app.models.user import User
from app.services.auth_service import EMAIL_PATTERN, PASSWORD_MIN_LENGTH, hash_password


OTP_LENGTH = 4
OTP_EXPIRY_SECONDS = 1 * 60
RESEND_COOLDOWN_SECONDS = 20

_OTP_STORE = {}
_OTP_LOCK = threading.RLock()


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _normalize_email(email):
    return _clean(email).lower()


def _now():
    return time.time()


def _otp_key(email):
    return _normalize_email(email)


def _cooldown_session_key(email):
    return f"forgot_password_cooldown_until::{_otp_key(email)}"


def _get_record_locked(email):
    record = _OTP_STORE.get(_otp_key(email))
    if not record:
        return None

    if record.get("used"):
        return None

    expires_at = record.get("expires_at", 0)
    if expires_at and expires_at < _now():
        _OTP_STORE.pop(_otp_key(email), None)
        return None

    return record


def _cleanup_record_locked(email):
    _OTP_STORE.pop(_otp_key(email), None)


def _store_cooldown_until(email, cooldown_until):
    normalized_email = _otp_key(email)
    until = float(cooldown_until or 0)

    with _OTP_LOCK:
        record = _OTP_STORE.get(normalized_email)
        if record is not None:
            record["resend_available_at"] = until

    session[_cooldown_session_key(normalized_email)] = until
    session.modified = True


def _get_effective_cooldown_until(email):
    normalized_email = _otp_key(email)
    record = _OTP_STORE.get(normalized_email) or {}
    record_until = float(record.get("resend_available_at") or 0)
    session_until = float(session.get(_cooldown_session_key(normalized_email)) or 0)
    return max(record_until, session_until)


def generate_otp():
    return f"{secrets.randbelow(10_000):04d}"


def send_otp_email(email, otp):
    message = Message(
        subject="Mã OTP đặt lại mật khẩu",
        recipients=[email],
        body=f"Mã OTP của bạn là {otp}. Mã này hết hạn sau 1 phút. Vui lòng không chia sẻ mã này.",
    )
    mail.send(message)


def save_otp(email, otp):
    normalized_email = _normalize_email(email)
    now = _now()
    record = {
        "email": normalized_email,
        "otp_hash": bcrypt.hashpw(otp.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        "created_at": now,
        "expires_at": now + OTP_EXPIRY_SECONDS,
        "resend_available_at": now + RESEND_COOLDOWN_SECONDS,
        "verified": False,
        "verified_at": None,
        "used": False,
        "attempts": 0,
    }

    with _OTP_LOCK:
        _OTP_STORE[normalized_email] = record

    return record


def _is_email_valid(email):
    return bool(EMAIL_PATTERN.fullmatch(_normalize_email(email)))


def _find_user_by_email(email):
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return None
    return User.query.filter(func.lower(User.email) == normalized_email).one_or_none()


def request_otp_for_email(email):
    normalized_email = _normalize_email(email)
    generic_payload = {"ok": True, "message": "Nếu email hợp lệ, mã OTP đã được gửi."}
    if not normalized_email or not _is_email_valid(normalized_email):
        return generic_payload, 200

    user = _find_user_by_email(normalized_email)
    if not user:
        return generic_payload, 200

    now = _now()
    cooldown_until = _get_effective_cooldown_until(normalized_email)
    if now < cooldown_until:
        retry_after = max(1, math.ceil(cooldown_until - now))
        return {
            "ok": False,
            "message": f"Vui lòng chờ {retry_after} giây trước khi yêu cầu mã mới.",
            "retry_after": retry_after,
            "cooldown_until": cooldown_until,
        }, 429

    otp = generate_otp()
    save_otp(normalized_email, otp)
    try:
        send_otp_email(normalized_email, otp)
    except Exception:
        current_app.logger.exception("Failed to send OTP email for %s", normalized_email)

    cooldown_until = now + RESEND_COOLDOWN_SECONDS
    _store_cooldown_until(normalized_email, cooldown_until)
    return {**generic_payload, "retry_after": RESEND_COOLDOWN_SECONDS, "cooldown_until": cooldown_until}, 200


def resend_otp_for_email(email):
    normalized_email = _normalize_email(email)
    generic_payload = {"ok": True, "message": "Nếu email hợp lệ, mã OTP đã được gửi lại."}
    if not normalized_email or not _is_email_valid(normalized_email):
        return generic_payload, 200

    user = _find_user_by_email(normalized_email)
    if not user:
        return generic_payload, 200

    now = _now()
    cooldown_until = _get_effective_cooldown_until(normalized_email)
    if now < cooldown_until:
        retry_after = max(1, math.ceil(cooldown_until - now))
        return {
            "ok": False,
            "message": f"Vui lòng chờ {retry_after} giây trước khi yêu cầu mã mới.",
            "retry_after": retry_after,
            "cooldown_until": cooldown_until,
        }, 429

    otp = generate_otp()
    save_otp(normalized_email, otp)
    try:
        send_otp_email(normalized_email, otp)
    except Exception:
        current_app.logger.exception("Failed to resend OTP email for %s", normalized_email)

    cooldown_until = _now() + RESEND_COOLDOWN_SECONDS
    _store_cooldown_until(normalized_email, cooldown_until)
    return {**generic_payload, "retry_after": RESEND_COOLDOWN_SECONDS, "cooldown_until": cooldown_until}, 200


def verify_otp_logic(email, otp):
    normalized_email = _normalize_email(email)
    candidate = _clean(otp)

    if not normalized_email or not _is_email_valid(normalized_email):
        return {"ok": False, "message": "Vui lòng nhập email hợp lệ."}, 400
    if not candidate or len(candidate) != OTP_LENGTH or not candidate.isdigit():
        return {"ok": False, "message": "Mã OTP không hợp lệ."}, 400

    with _OTP_LOCK:
        record = _get_record_locked(normalized_email)
        if not record:
            return {"ok": False, "message": "Mã OTP không tồn tại hoặc đã hết hạn."}, 400

        record["attempts"] = int(record.get("attempts", 0)) + 1

        if _now() > record.get("expires_at", 0):
            _cleanup_record_locked(normalized_email)
            return {"ok": False, "message": "Mã OTP đã hết hạn."}, 400

        otp_hash = record.get("otp_hash") or ""
        try:
            matched = bcrypt.checkpw(candidate.encode("utf-8"), otp_hash.encode("utf-8"))
        except ValueError:
            matched = False

        if not matched:
            return {"ok": False, "message": "Mã OTP không chính xác."}, 400

        record["verified"] = True
        record["verified_at"] = _now()
        record["used"] = True

    return {"ok": True, "message": "Xác minh OTP thành công. Bạn có thể đặt lại mật khẩu."}, 200


def can_reset_password(email):
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return False

    with _OTP_LOCK:
        record = _OTP_STORE.get(normalized_email)
        if not record or not record.get("verified"):
            return False
        if record.get("used") is not True:
            return False
        if record.get("expires_at", 0) < _now():
            _cleanup_record_locked(normalized_email)
            return False
        return True


def reset_password_for_email(email, new_password, confirm_password=None):
    normalized_email = _normalize_email(email)
    password = new_password or ""
    confirm = confirm_password if confirm_password is not None else None

    if not normalized_email or not _is_email_valid(normalized_email):
        return {"ok": False, "message": "Vui lòng nhập email hợp lệ."}, 400
    if len(password) < PASSWORD_MIN_LENGTH:
        return {"ok": False, "message": f"Mật khẩu mới tối thiểu {PASSWORD_MIN_LENGTH} ký tự."}, 400
    if confirm is not None:
        confirm_value = confirm or ""
        if len(confirm_value) < PASSWORD_MIN_LENGTH:
            return {"ok": False, "message": f"Mật khẩu xác nhận tối thiểu {PASSWORD_MIN_LENGTH} ký tự."}, 400
        if confirm_value != password:
            return {"ok": False, "message": "Mật khẩu nhập lại không khớp."}, 400

    user = _find_user_by_email(normalized_email)
    if not user:
        return {"ok": True, "message": "Nếu xác minh hợp lệ, mật khẩu đã được cập nhật."}, 200

    if not can_reset_password(normalized_email):
        return {"ok": False, "message": "Phiên đặt lại mật khẩu không hợp lệ hoặc đã hết hạn."}, 400

    user.password = hash_password(password)
    db.session.commit()

    with _OTP_LOCK:
        _cleanup_record_locked(normalized_email)

    session.pop(_cooldown_session_key(normalized_email), None)
    session.modified = True
    return {"ok": True, "message": "Mật khẩu đã được cập nhật thành công."}, 200
