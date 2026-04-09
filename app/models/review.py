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

    customer = db.relationship("Customer", back_populates="reviews")
    restaurant = db.relationship("Restaurant", back_populates="reviews")
