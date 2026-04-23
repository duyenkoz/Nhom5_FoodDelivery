from datetime import datetime

from app.extensions import db


class Order(db.Model):
    __tablename__ = "orders"

    order_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.customer_id"), nullable=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey("vouchers.voucher_id"), nullable=True)
    order_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
    shipping_at = db.Column(db.DateTime, nullable=True)
    total_amount = db.Column(db.Integer, nullable=True)
    delivery_fee = db.Column(db.Integer, nullable=True)
    delivery_address = db.Column(db.String(200), nullable=True)
    note = db.Column(db.String(300), nullable=True)
    status = db.Column(db.String(50), nullable=True)
    cancel_reason = db.Column(db.String(300), nullable=True)
    cancel_request_status = db.Column(db.String(30), nullable=True)
    cancel_request_reason = db.Column(db.String(300), nullable=True)
    cancel_request_date = db.Column(db.DateTime, nullable=True)
    cancel_request_handled_at = db.Column(db.DateTime, nullable=True)
    cancel_request_handled_by = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=True)
    cancel_request_admin_note = db.Column(db.String(300), nullable=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.restaurant_id"), nullable=True)

    customer = db.relationship("Customer", back_populates="orders")
    voucher = db.relationship("Voucher", back_populates="orders")
    restaurant = db.relationship("Restaurant", back_populates="orders")
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payment = db.relationship("Payment", back_populates="order", uselist=False)
