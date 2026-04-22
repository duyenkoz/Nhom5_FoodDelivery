from app.extensions import db


class OrderItem(db.Model):
    __tablename__ = "orderitems"

    order_item_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.order_id"), nullable=True)
    dish_id = db.Column(db.Integer, db.ForeignKey("dishes.dish_id"), nullable=True)
    quantity = db.Column(db.Integer, nullable=True)
    price = db.Column(db.Integer, nullable=True)

    order = db.relationship("Order", back_populates="items")
    dish = db.relationship("Dish", back_populates="order_items")
