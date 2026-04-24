from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from datetime import datetime

from app.extensions import db
from app.models.review import Review
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.voucher import Voucher
from app.services.admin_service import build_admin_context, save_voucher_for_admin
from app.services.restaurant_service import process_cancel_request_for_admin
from app.services.shipping_service import get_shipping_fee_settings, save_shipping_fee_settings
from app.services.system_setting_service import set_setting

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
    type_filter = request.args.get("type", "all").strip() or "all"
    state_filter = request.args.get("state", "all").strip() or "all"
    period = request.args.get("period", "month").strip() or "month"
    report_date = request.args.get("date", "").strip()
    report_month = request.args.get("month", "").strip()
    report_year = request.args.get("year", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sentiment = request.args.get("sentiment", "all").strip() or "all"
    rating = request.args.get("rating", "all").strip() or "all"
    page = request.args.get("page", default=1, type=int)
    context = build_admin_context(
        section_name,
        query=query,
        role_filter=role_filter,
        type_filter=type_filter,
        state_filter=state_filter,
        period=period,
        report_date=report_date,
        report_month=report_month,
        report_year=report_year,
        date_from=date_from,
        date_to=date_to,
        sentiment=sentiment,
        rating=rating,
        page=page,
    )
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


@bp.route("/vouchers/create", methods=["POST"])
def create_voucher():
    if not _require_admin():
        return _login_redirect()

    search_query = (request.form.get("q") or request.args.get("q", "")).strip()
    try:
        voucher = save_voucher_for_admin(session.get("user_id"), request.form)
    except ValueError as exc:
        form_errors = exc.args[0] if exc.args else {}
        form_values = dict(request.form)
        if not form_values.get("status"):
            form_values["status"] = ""
        context = build_admin_context("vouchers", query=search_query)
        return render_template(
            "admin/dashboard.html",
            show_search=False,
            show_auth=False,
            admin_voucher_form_values=form_values,
            admin_voucher_form_errors=form_errors,
            **context,
        )

    flash(f"Đã tạo voucher {voucher.voucher_code}.", "success")
    return redirect(url_for("admin.vouchers", q=search_query))


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


@bp.route("/reports")
def reports():
    return _render_admin("reports")


@bp.route("/search-settings", methods=["GET", "POST", "PUT"])
def search_settings():
    if not _require_admin():
        return _login_redirect()

    def _payload():
        if request.is_json:
            data = request.get_json(silent=True)
            return data if isinstance(data, dict) else {}
        return request.form

    if request.method in {"POST", "PUT"}:
        payload = _payload()
        raw_radius = payload.get("search_radius_km")
        try:
            search_radius_km = int(str(raw_radius).strip())
            if search_radius_km < 1:
                raise ValueError
        except (TypeError, ValueError):
            message = "Bán kính tìm kiếm phải là số nguyên lớn hơn 0."
            if request.method == "PUT" or request.is_json:
                return jsonify({"ok": False, "message": message}), 400

            context = build_admin_context("search_settings")
            return render_template(
                "admin/dashboard.html",
                show_search=False,
                show_auth=False,
                admin_search_radius_km_value=raw_radius or context.get("search_radius_km", 5),
                admin_search_radius_km_error=message,
                **context,
            )

        set_setting("SEARCH_RADIUS_KM", search_radius_km)
        if request.method == "PUT" or request.is_json:
            return jsonify({"ok": True, "search_radius_km": search_radius_km})

        flash("Đã cập nhật bán kính tìm kiếm.", "success")
        return redirect(url_for("admin.search_settings"))

    return _render_admin("search_settings")


@bp.route("/shipping-rules", methods=["GET", "POST"])
def shipping_rules():
    if not _require_admin():
        return _login_redirect()

    if request.method == "POST":
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
        return redirect(url_for("admin.shipping_rules"))

    return _render_admin("shipping_rules")


@bp.route("/shipping-fees", methods=["GET", "POST"])
def shipping_fees():
    if not _require_admin():
        return _login_redirect()

    def _shipping_fees_redirect():
        return redirect(
            url_for(
                "admin.shipping_fees",
                q=request.args.get("q", ""),
                page=request.args.get("page", 1),
                role=request.args.get("role", "all"),
            )
        )

    if request.method == "POST":
        form_type = (request.form.get("form_type") or "").strip()
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
                current_fee = restaurant.platform_fee or 0
                if current_fee == normalized_fee:
                    continue
                restaurant.platform_fee = normalized_fee
                updated_count += 1

            db.session.commit()
            if updated_count:
                flash(f"Đã áp dụng phí sàn {normalized_fee:,}đ cho {updated_count} nhà hàng ở khu vực {area}.", "success")
            else:
                flash(f"Không có nhà hàng nào ở khu vực {area} cần thay đổi phí sàn.", "info")
            return _shipping_fees_redirect()

        restaurant_ids = request.form.getlist("restaurant_id")
        fee_values = request.form.getlist("platform_fee")
        updated_count = 0

        for restaurant_id, fee_value in zip(restaurant_ids, fee_values):
            restaurant = db.session.get(Restaurant, restaurant_id)
            if not restaurant:
                continue
            try:
                next_fee = max(0, int(fee_value))
            except (TypeError, ValueError):
                next_fee = 0
            current_fee = restaurant.platform_fee or 0
            if current_fee == next_fee:
                continue
            restaurant.platform_fee = next_fee
            updated_count += 1

        db.session.commit()
        if updated_count:
            flash(f"Đã cập nhật phí sàn cho {updated_count} nhà hàng.", "success")
        else:
            flash("Không có nhà hàng nào thay đổi phí sàn.", "info")
        return _shipping_fees_redirect()

    return _render_admin("shipping_fees")


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


@bp.route("/cancel-requests/<int:order_id>/approve", methods=["POST"])
def approve_cancel_request(order_id):
    if not _require_admin():
        return _login_redirect()

    note = _clean_text(request.form.get("note"))
    order, status, _ = process_cancel_request_for_admin(
        order_id,
        approved=True,
        admin_user_id=session.get("user_id"),
        admin_note=note,
    )
    if not order:
        flash("Không tìm thấy đơn hàng có yêu cầu hủy.", "error")
    elif status == "no_pending_request":
        flash("Đơn hàng này không còn yêu cầu hủy đang chờ duyệt.", "warning")
    elif status in {"refund_pending", "cancelled"}:
        flash(f"Đã duyệt yêu cầu hủy đơn #{order.order_id}.", "success")
    else:
        flash("Không thể duyệt yêu cầu hủy lúc này.", "error")

    return redirect(url_for("admin.disputes", **request.args))


@bp.route("/cancel-requests/<int:order_id>/reject", methods=["POST"])
def reject_cancel_request(order_id):
    if not _require_admin():
        return _login_redirect()

    note = _clean_text(request.form.get("note"))
    order, status, _ = process_cancel_request_for_admin(
        order_id,
        approved=False,
        admin_user_id=session.get("user_id"),
        admin_note=note,
    )
    if not order:
        flash("Không tìm thấy đơn hàng có yêu cầu hủy.", "error")
    elif status == "no_pending_request":
        flash("Đơn hàng này không còn yêu cầu hủy đang chờ duyệt.", "warning")
    elif status == "rejected":
        flash(f"Đã từ chối yêu cầu hủy đơn #{order.order_id}.", "success")
    else:
        flash("Không thể từ chối yêu cầu hủy lúc này.", "error")

    return redirect(url_for("admin.disputes", **request.args))


def _clean_text(value):
    return value.strip() if isinstance(value, str) else ""


def _clean_status(value):
    return _clean_text(value).lower()
