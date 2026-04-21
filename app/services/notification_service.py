import json

from flask import url_for
from sqlalchemy import inspect

from app.extensions import db, socketio
from app.models.notification import Notification
from app.utils.time_utils import format_vietnam_datetime, to_vietnam_datetime


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _notification_table_ready():
    try:
        return inspect(db.engine).has_table(Notification.__tablename__)
    except Exception:
        return False


def _payload_dict(notification):
    try:
        return json.loads(notification.payload_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def serialize_notification(notification):
    payload = _payload_dict(notification)
    created_at_vn = to_vietnam_datetime(notification.created_at)
    return {
        "notification_id": notification.notification_id,
        "type": notification.type or "",
        "title": notification.title,
        "message": notification.message,
        "link": notification.link or "",
        "payload": payload,
        "is_read": bool(notification.is_read),
        "created_at": created_at_vn.isoformat() if created_at_vn else "",
        "created_at_text": format_vietnam_datetime(notification.created_at, "%d/%m %H:%M"),
    }


def get_user_notifications(user_id, unread_only=False, limit=8):
    if not user_id:
        return []
    if not _notification_table_ready():
        return []

    query = Notification.query.filter(Notification.user_id == user_id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))

    notifications = query.order_by(Notification.created_at.desc(), Notification.notification_id.desc()).limit(limit).all()
    return [serialize_notification(notification) for notification in notifications]


def get_user_notification_count(user_id):
    if not user_id:
        return 0
    if not _notification_table_ready():
        return 0
    return Notification.query.filter(Notification.user_id == user_id, Notification.is_read.is_(False)).count()


def create_notification(user_id, title, message, link="", type="general", payload=None):
    if not user_id:
        return None
    if not _notification_table_ready():
        try:
            Notification.__table__.create(bind=db.engine, checkfirst=True)
        except Exception:
            return None

    notification = Notification(
        user_id=user_id,
        type=_clean(type) or "general",
        title=_clean(title) or "Thông báo",
        message=_clean(message) or "",
        link=_clean(link) or "",
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
        is_read=False,
    )
    db.session.add(notification)
    db.session.commit()

    socketio.emit("notification:new", serialize_notification(notification), room=f"user_{user_id}")
    return notification


def mark_notification_read(user_id, notification_id):
    if not user_id or not notification_id:
        return None
    if not _notification_table_ready():
        return None

    notification = Notification.query.filter_by(notification_id=notification_id, user_id=user_id).one_or_none()
    if not notification:
        return None

    if not notification.is_read:
        notification.is_read = True
        db.session.commit()

    return notification


def build_order_created_notification(order, customer_name="", payment_method_label=""):
    if not order or not order.restaurant_id:
        return None

    return {
        "user_id": order.restaurant_id,
        "type": "restaurant_new_order",
        "title": f"Đơn mới #{order.order_id}",
        "message": f"{customer_name or 'Khách hàng'} vừa đặt hàng.",
        "link": url_for("restaurant.orders", focus=order.order_id),
        "payload": {
            "order_id": order.order_id,
            "restaurant_id": order.restaurant_id,
            "customer_name": customer_name,
        },
    }


def build_order_confirmed_notification(order, restaurant_name=""):
    if not order or not order.customer_id:
        return None

    return {
        "user_id": order.customer_id,
        "type": "customer_order_confirmed",
        "title": f"Đơn #{order.order_id} đã được xác nhận",
        "message": f"{restaurant_name or 'Nhà hàng'} đã xác nhận đơn của bạn.",
        "link": url_for("auth.order_detail", order_id=order.order_id),
        "payload": {
            "order_id": order.order_id,
            "restaurant_name": restaurant_name,
        },
    }


def build_order_cancelled_notification(order, cancel_reason="", restaurant_name=""):
    if not order or not order.customer_id:
        return None

    return {
        "user_id": order.customer_id,
        "type": "customer_order_cancelled",
        "title": f"Đơn #{order.order_id} đã bị hủy",
        "message": f"{restaurant_name or 'Nhà hàng'} đã hủy đơn của bạn.",
        "link": url_for("auth.order_detail", order_id=order.order_id),
        "payload": {
            "order_id": order.order_id,
            "restaurant_name": restaurant_name,
            "cancel_reason": cancel_reason,
        },
    }


def emit_structured_notification(notification_data):
    if not notification_data:
        return None

    return create_notification(
        notification_data["user_id"],
        notification_data["title"],
        notification_data["message"],
        link=notification_data.get("link", ""),
        type=notification_data.get("type", "general"),
        payload=notification_data.get("payload", {}),
    )
