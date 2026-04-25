from flask import Blueprint, jsonify, request, session

from app.services.notification_service import (
    get_user_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


def _require_login():
    return session.get("auth_state") == "logged_in" and session.get("user_id")


@bp.route("", methods=["GET"])
def list_notifications():
    if not _require_login():
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập lại."}), 401

    unread_only = request.args.get("unread_only", "1") != "0"
    limit = request.args.get("limit", type=int) or 8
    return jsonify(
        {
            "ok": True,
            "notifications": get_user_notifications(session.get("user_id"), unread_only=unread_only, limit=limit),
        }
    )


@bp.route("/<int:notification_id>/read", methods=["POST"])
def read_notification(notification_id):
    if not _require_login():
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập lại."}), 401

    notification = mark_notification_read(session.get("user_id"), notification_id)
    if not notification:
        return jsonify({"ok": False, "message": "Không tìm thấy thông báo."}), 404
    return jsonify({"ok": True})


@bp.route("/read-all", methods=["POST"])
def read_all_notifications():
    if not _require_login():
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập lại."}), 401

    updated_count = mark_all_notifications_read(session.get("user_id"))
    return jsonify({"ok": True, "updated_count": updated_count})
