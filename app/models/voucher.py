from app.extensions import db


class Voucher(db.Model):
    __tablename__ = "vouchers"

    voucher_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    voucher_code = db.Column(db.String(50), nullable=True)
    discount_type = db.Column(
        db.Enum("amount", "percent", name="voucher_discount_type"),
        nullable=True,
    )
    discount_value = db.Column(db.Integer, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=True)
    voucher_scope = db.Column(
        db.Enum("system", "restaurant", name="voucher_scope"),
        nullable=True,
    )
    status = db.Column(db.Boolean, nullable=True)

    creator = db.relationship("User", back_populates="created_vouchers")
    orders = db.relationship("Order", back_populates="voucher")
