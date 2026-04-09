from app.extensions import db


class Restaurant(db.Model):
    __tablename__ = "restaurants"

    restaurant_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id"),
        primary_key=True,
        autoincrement=False,
    )
    image = db.Column(db.String(255), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    area = db.Column(db.String(100), nullable=True)
    description = db.Column(db.String(500), nullable=True)
    platform_fee = db.Column(db.Integer, nullable=True)

    user = db.relationship("User", back_populates="restaurant_profile")
    dishes = db.relationship("Dish", back_populates="restaurant", order_by="Dish.dish_id")
    carts = db.relationship("Cart", back_populates="restaurant")
    orders = db.relationship("Order", back_populates="restaurant")
    reviews = db.relationship("Review", back_populates="restaurant")
