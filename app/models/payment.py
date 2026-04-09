from datetime import datetime

from app.extensions import db


class Payment(db.Model):
    __tablename__ = "payments"

    payment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.order_id"), nullable=True)
    payment_method = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(50), nullable=True)
    payment_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)

    order = db.relationship("Order", back_populates="payment")
