from app.extensions import db


class Customer(db.Model):
    __tablename__ = "customers"

    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id"),
        primary_key=True,
        autoincrement=False,
    )
    address = db.Column(db.String(200), nullable=True)
    area = db.Column(db.String(100), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    user = db.relationship("User", back_populates="customer_profile")
    carts = db.relationship("Cart", back_populates="customer")
    orders = db.relationship("Order", back_populates="customer")
    reviews = db.relationship("Review", back_populates="customer")
