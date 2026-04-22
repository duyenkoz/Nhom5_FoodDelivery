from app.extensions import db


class Dish(db.Model):
    __tablename__ = "dishes"

    dish_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.restaurant_id"), nullable=True)
    dish_name = db.Column(db.String(100), nullable=True)
    category = db.Column(db.String(80), nullable=True)
    image = db.Column(db.String(255), nullable=True)
    price = db.Column(db.Integer, nullable=True)
    description = db.Column(db.String(300), nullable=True)
    status = db.Column(db.Boolean, nullable=True, default=True)

    restaurant = db.relationship("Restaurant", back_populates="dishes")
    cart_items = db.relationship("CartItem", back_populates="dish")
    order_items = db.relationship("OrderItem", back_populates="dish")
