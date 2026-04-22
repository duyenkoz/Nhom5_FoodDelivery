from app.extensions import db


class CartItem(db.Model):
    __tablename__ = "cartitems"

    cart_item_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("carts.cart_id"), nullable=True)
    dish_id = db.Column(db.Integer, db.ForeignKey("dishes.dish_id"), nullable=True)
    quantity = db.Column(db.Integer, nullable=True)
    price = db.Column(db.Integer, nullable=True)
    note = db.Column(db.String(255), nullable=True)

    cart = db.relationship("Cart", back_populates="items")
    dish = db.relationship("Dish", back_populates="cart_items")
