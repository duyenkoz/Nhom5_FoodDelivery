from datetime import datetime

from app.extensions import db


class Review(db.Model):
    __tablename__ = "reviews"

    review_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.customer_id"), nullable=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.restaurant_id"), nullable=True)
    rating = db.Column(db.Integer, nullable=True)
    comment = db.Column(db.String(500), nullable=True)
    sentiment = db.Column(db.String(50), nullable=True)
    review_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
    report_status = db.Column(db.String(20), default="none", nullable=False)
    report_reason = db.Column(db.String(300), nullable=True)
    report_date = db.Column(db.DateTime, nullable=True)
    report_handled_at = db.Column(db.DateTime, nullable=True)
    report_admin_action = db.Column(db.String(20), nullable=True)
    report_admin_note = db.Column(db.String(300), nullable=True)
    report_handled_by = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=True)

    customer = db.relationship("Customer", back_populates="reviews")
    restaurant = db.relationship("Restaurant", back_populates="reviews")
