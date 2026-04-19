from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from datetime import datetime

from app.extensions import db
from app.models.review import Review
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.voucher import Voucher
from app.services.admin_service import build_admin_context
from app.services.shipping_service import get_shipping_fee_settings, save_shipping_fee_settings

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _require_admin():
    return session.get("auth_state") == "logged_in" and session.get("user_role") == "admin"


def _login_redirect():
    flash("Vui lòng đăng nhập tài khoản quản trị để tiếp tục.", "warning")
    return redirect(url_for("auth.login", next=url_for("admin.dashboard")))


def _render_admin(section_name):
    if not _require_admin():
        return _login_redirect()

    query = request.args.get("q", "").strip()
    role_filter = request.args.get("role", "all").strip() or "all"
    page = request.args.get("page", default=1, type=int)
    context = build_admin_context(section_name, query=query, role_filter=role_filter, page=page)
    return render_template(
        "admin/dashboard.html",
        show_search=False,
        show_auth=False,
        **context,
    )


@bp.route("/")
def index():
    if _require_admin():
        return redirect(url_for("admin.dashboard"))
    return _login_redirect()


@bp.route("/dashboard")
def dashboard():
    return _render_admin("dashboard")


@bp.route("/accounts")
def accounts():
    return _render_admin("accounts")


@bp.route("/vouchers")
def vouchers():
    return _render_admin("vouchers")


@bp.route("/reviews")
def reviews():
    return _render_admin("reviews")


@bp.route("/complaints")
def complaints():
    return _render_admin("complaints")


@bp.route("/review-reports")
def review_reports():
    return _render_admin("review_reports")


@bp.route("/disputes")
def disputes():
    return _render_admin("disputes")


@bp.route("/shipping-fees", methods=["GET", "POST"])
def shipping_fees():
    if not _require_admin():
        return _login_redirect()

    if request.method == "POST":
        form_type = (request.form.get("form_type") or "").strip()

        if form_type == "shipping_rules":
            existing_floor_fee = get_shipping_fee_settings().get("floor_fee", 0)
            min_km_values = request.form.getlist("min_km")
            max_km_values = request.form.getlist("max_km")
            fee_values = request.form.getlist("fee")
            rules = []
            for min_km, max_km, fee in zip(min_km_values, max_km_values, fee_values):
                rules.append(
                    {
                        "min_km": min_km,
                        "max_km": max_km,
                        "fee": fee,
                    }
                )
            save_shipping_fee_settings({"floor_fee": existing_floor_fee, "rules": rules})
            flash("Đã cập nhật phí ship theo khoảng cách.", "success")
            return redirect(url_for("admin.shipping_fees"))

        if form_type == "bulk_apply_area":
            area = (request.form.get("area") or "").strip()
            fee_value = request.form.get("platform_fee", 0)
            if not area:
                flash("Vui lòng chọn khu vực trước khi áp dụng đồng loạt.", "warning")
                return redirect(url_for("admin.shipping_fees", **request.args))

            try:
                normalized_fee = max(0, int(fee_value))
            except (TypeError, ValueError):
                normalized_fee = 0

            restaurants = Restaurant.query.filter(Restaurant.area == area).all()
            updated_count = 0
            for restaurant in restaurants:
                restaurant.platform_fee = normalized_fee
                updated_count += 1

            db.session.commit()
            flash(f"Đã áp dụng phí sàn {normalized_fee:,}đ cho {updated_count} nhà hàng ở khu vực {area}.", "success")
            return redirect(url_for("admin.shipping_fees", q=request.args.get("q", ""), page=request.args.get("page", 1), role=request.args.get("role", "all")))

        restaurant_ids = request.form.getlist("restaurant_id")
        fee_values = request.form.getlist("platform_fee")
        updated_count = 0

        for restaurant_id, fee_value in zip(restaurant_ids, fee_values):
            restaurant = db.session.get(Restaurant, restaurant_id)
            if not restaurant:
                continue
            try:
                restaurant.platform_fee = max(0, int(fee_value))
            except (TypeError, ValueError):
                restaurant.platform_fee = 0
            updated_count += 1

        db.session.commit()
        flash(f"Đã cập nhật phí sàn cho {updated_count} nhà hàng.", "success")
        return redirect(url_for("admin.shipping_fees"))

    return _render_admin("shipping")


@bp.route("/accounts/<int:user_id>/toggle-status", methods=["POST"])
def toggle_account_status(user_id):
    if not _require_admin():
        return _login_redirect()

    user = db.session.get(User, user_id)
    if not user:
        flash("Không tìm thấy tài khoản.", "error")
        return redirect(url_for("admin.accounts", **request.args))

    if session.get("user_id") == user.user_id:
        flash("Không thể tự khoá tài khoản quản trị đang đăng nhập.", "error")
        return redirect(url_for("admin.accounts", **request.args))

    user.status = not bool(user.status)
    db.session.commit()
    flash(f"Đã {'kích hoạt' if user.status else 'tạm khoá'} tài khoản {user.display_name or user.username}.", "success")
    return redirect(url_for("admin.accounts", **request.args))


@bp.route("/vouchers/<int:voucher_id>/toggle-status", methods=["POST"])
def toggle_voucher_status(voucher_id):
    if not _require_admin():
        return _login_redirect()

    voucher = db.session.get(Voucher, voucher_id)
    if not voucher:
        flash("Không tìm thấy voucher.", "error")
        return redirect(url_for("admin.vouchers", **request.args))

    voucher.status = not bool(voucher.status)
    db.session.commit()
    flash(f"Đã {'bật' if voucher.status else 'tắt'} voucher {voucher.voucher_code or voucher.voucher_id}.", "success")
    return redirect(url_for("admin.vouchers", **request.args))


@bp.route("/review-reports/<int:review_id>/dismiss", methods=["POST"])
def dismiss_review_report(review_id):
    if not _require_admin():
        return _login_redirect()

    review = db.session.get(Review, review_id)
    if not review or _clean_status(review.report_status) != "pending":
        flash("Không tìm thấy báo cáo đánh giá đang chờ xử lý.", "error")
        return redirect(url_for("admin.review_reports", **request.args))

    review.report_status = "dismissed"
    review.report_admin_action = "dismissed"
    review.report_admin_note = _clean_text(request.form.get("note")) or "Admin đã bỏ qua báo cáo."
    review.report_handled_at = datetime.utcnow()
    review.report_handled_by = session.get("user_id")
    db.session.commit()
    flash("Đã bỏ qua báo cáo đánh giá.", "success")
    return redirect(url_for("admin.review_reports", **request.args))


@bp.route("/review-reports/<int:review_id>/delete", methods=["POST"])
def delete_reported_review(review_id):
    if not _require_admin():
        return _login_redirect()

    review = db.session.get(Review, review_id)
    if not review:
        flash("Không tìm thấy đánh giá để xoá.", "error")
        return redirect(url_for("admin.review_reports", **request.args))

    db.session.delete(review)
    db.session.commit()
    flash("Đã xoá đánh giá khỏi hệ thống.", "success")
    return redirect(url_for("admin.review_reports", **request.args))


def _clean_text(value):
    return value.strip() if isinstance(value, str) else ""


def _clean_status(value):
    return _clean_text(value).lower()
