from datetime import datetime, timedelta

from app.extensions import db
from app.services.notification_service import (
    build_order_completed_notification,
    build_restaurant_order_completed_notification,
    emit_structured_notification,
)


def refresh_simulated_order_state(order):
    if not order or not order.order_date:
        return order

    raw_status = (order.status or "").strip().lower()
    now = datetime.utcnow()
    changed = False
    shipping_started_at = getattr(order, "shipping_at", None) or order.order_date

    if raw_status == "pending_payment":
        if now >= order.order_date + timedelta(minutes=10):
            order.status = "cancelled"
            if order.payment and (order.payment.status or "").lower() != "paid":
                order.payment.status = "cancelled"
            changed = True

    elif raw_status == "shipping":
        if shipping_started_at and now >= shipping_started_at + timedelta(minutes=1):
            order.status = "completed"
            if order.payment and (order.payment.status or "").lower() != "paid":
                order.payment.status = "paid"
            changed = True

    if changed:
        db.session.commit()
        if raw_status == "shipping" and (order.status or "").strip().lower() == "completed":
            restaurant_name = ""
            customer_name = ""
            if order.restaurant and order.restaurant.user:
                restaurant_name = order.restaurant.user.display_name or order.restaurant.user.username or ""
            if order.customer and order.customer.user:
                customer_name = order.customer.user.display_name or order.customer.user.username or ""
            emit_structured_notification(build_order_completed_notification(order, restaurant_name=restaurant_name))
            emit_structured_notification(
                build_restaurant_order_completed_notification(order, customer_name=customer_name)
            )
    return order
