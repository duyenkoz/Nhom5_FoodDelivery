from datetime import datetime

from app.extensions import db


class Cart(db.Model):
    __tablename__ = "carts"

    cart_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.customer_id"), nullable=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.restaurant_id"), nullable=True)
    total_amount = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)

    customer = db.relationship("Customer", back_populates="carts")
    restaurant = db.relationship("Restaurant", back_populates="carts")
    items = db.relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")
