from flask_login import UserMixin

from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(100), unique=True, nullable=True, index=True)
    phone = db.Column(db.String(20), nullable=True)
    role = db.Column(
        db.Enum("admin", "customer", "restaurant", name="user_role"),
        nullable=True,
    )
    status = db.Column(db.Boolean, nullable=True, default=True)

    customer_profile = db.relationship(
        "Customer",
        back_populates="user",
        uselist=False,
    )
    restaurant_profile = db.relationship(
        "Restaurant",
        back_populates="user",
        uselist=False,
    )
    created_vouchers = db.relationship("Voucher", back_populates="creator")
    notifications = db.relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    def get_id(self):
        return str(self.user_id)
