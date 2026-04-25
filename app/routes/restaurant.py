from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from flask import jsonify
from app.services.ai_review_summary_service import (
    ReviewSummaryConfigError,
    ReviewSummaryRequestError,
    generate_restaurant_review_improvement_insights,
    get_ai_review_summary_settings,
    query_negative_reviews_for_improvement_insights,
)
from app.services.restaurant_service import (
    build_dashboard_context,
    build_section_context,
    cancel_order_for_restaurant,
    delete_dish_for_restaurant,
    delete_voucher_for_restaurant,
    confirm_order_for_restaurant,
    complete_order_for_restaurant,
    request_cancel_order_for_restaurant,
    withdraw_cancel_request_for_restaurant,
    report_review_for_restaurant,
    save_dish_for_restaurant,
    save_voucher_for_restaurant,
    toggle_dish_status_for_restaurant,
    toggle_voucher_status_for_restaurant,
    get_restaurant_by_user_id,
)
from app.services.notification_service import (
    build_order_cancelled_notification,
    build_order_confirmed_notification,
    build_order_shipping_notification,
    emit_structured_notification,
)

bp = Blueprint("restaurant", __name__, url_prefix="/restaurant")


def _require_restaurant():
    if session.get("auth_state") != "logged_in" or session.get("user_role") != "restaurant":
        return False
    return True


def _render_section(section_name):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    context = build_section_context(
        session.get("user_id"),
        section_name,
        query=request.args.get("q", "").strip(),
        order_status=request.args.get("status", "all").strip() or "all",
        sort=request.args.get("sort", "desc").strip() or "desc",
        date_from=request.args.get("date_from", request.args.get("start", "")).strip(),
        date_to=request.args.get("date_to", request.args.get("end", "")).strip(),
        review_sentiment=request.args.get("sentiment", "all").strip() or "all",
        review_rating=request.args.get("rating", "all").strip() or "all",
        focus_order_id=request.args.get("focus", type=int),
        page=request.args.get("page", default=1, type=int),
        analytics_period=request.args.get("period", "month").strip() or "month",
        analytics_date=request.args.get("date", "").strip(),
        analytics_month=request.args.get("month", "").strip(),
        analytics_year=request.args.get("year", "").strip(),
        analytics_trend_period=request.args.get("trend_period", "month").strip() or "month",
        analytics_top_period=request.args.get("top_period", "month").strip() or "month",
    )
    if context["restaurant"] is None:
        flash("Vui lòng hoàn thiện thông tin nhà hàng trước khi vào khu quản trị.", "warning")
        return redirect(url_for("auth.complete_restaurant"))

    template_map = {
        "orders": "restaurant/restaurant_orders.html",
        "analytics": "restaurant/restaurant_analytics.html",
        "vouchers": "restaurant/restaurant_voucher_manage.html",
    }

    return render_template(
        template_map.get(section_name, "restaurant/section_v2.html"),
        show_search=False,
        show_auth=False,
        **context,
    )


@bp.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    user_id = session.get("user_id")
    edit_dish_id = request.args.get("edit", type=int)
    search_query = request.args.get("q", "").strip()
    active_category = request.args.get("category", "all").strip() or "all"
    page = request.args.get("page", default=1, type=int)

    if request.method == "POST":
        search_query = (request.form.get("q") or search_query).strip()
        active_category = (request.form.get("filter_category") or active_category).strip() or "all"
        page = request.form.get("page", type=int) or page
        try:
            dish, action = save_dish_for_restaurant(user_id, request.form, request.files.get("dish_image"))
        except ValueError as exc:
            form_errors = exc.args[0] if exc.args else {}
            form_values = dict(request.form)
            if not form_values.get("status"):
                form_values["status"] = ""
            if "status" not in form_values:
                form_values["status"] = ""
            if form_values.get("dish_id"):
                edit_dish_id = int(form_values["dish_id"])
            search_query = form_values.get("q", search_query)
            active_category = form_values.get("filter_category", active_category)
            page = int(form_values.get("page") or page or 1)
            context = build_dashboard_context(
                user_id,
                edit_dish_id=edit_dish_id,
                form_values=form_values,
                form_errors=form_errors,
                query=search_query,
                category=active_category,
                page=page,
            )
            return render_template(
                "restaurant/restaurant_menu_manage.html",
                show_search=False,
                show_auth=False,
                **context,
            )

        flash(f"Đã {action} món \"{dish.dish_name}\".", "success")
        return redirect(url_for("restaurant.dashboard", q=search_query, category=active_category, page=page))

    context = build_dashboard_context(
        user_id,
        edit_dish_id=edit_dish_id,
        query=search_query,
        category=active_category,
        page=page,
    )
    if context["restaurant"] is None:
        flash("Vui lòng hoàn thiện thông tin nhà hàng trước khi quản lý thực đơn.", "warning")
        return redirect(url_for("auth.complete_restaurant"))

    return render_template(
        "restaurant/restaurant_menu_manage.html",
        show_search=False,
        show_auth=False,
        **context,
    )


@bp.route("/orders")
def orders():
    return _render_section("orders")


@bp.route("/orders/<int:order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    order, status = confirm_order_for_restaurant(session.get("user_id"), order_id)
    if status == "not_found":
        flash("Không tìm thấy đơn hàng để xác nhận.", "error")
    elif status == "cancelled":
        flash("Đơn hàng này đã bị hủy trước đó.", "warning")
    elif status == "refund_pending":
        flash("Đơn hàng này đang ở trạng thái Chờ hoàn tiền.", "warning")
    elif status == "completed":
        flash("Đơn hàng đã ở trạng thái hoàn thành.", "warning")
    elif order:
        restaurant_name = session.get("user_display_name") or session.get("username") or "Nhà hàng"
        notification_data = build_order_confirmed_notification(order, restaurant_name=restaurant_name)
        emit_structured_notification(notification_data)
        flash(f"Đã chuyển đơn #{order.order_id} sang trạng thái Đang chuẩn bị.", "success")
    else:
        flash("Không thể xác nhận đơn hàng lúc này.", "error")

    return redirect(
        url_for(
            "restaurant.orders",
            q=request.values.get("q", ""),
            status=request.values.get("status", "all"),
            sort=request.values.get("sort", "desc"),
            start=request.values.get("start", ""),
            end=request.values.get("end", ""),
            focus=request.values.get("focus", ""),
            page=request.values.get("page", 1),
        )
    )


@bp.route("/orders/<int:order_id>/complete", methods=["POST"])
def complete_order(order_id):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    order, status = complete_order_for_restaurant(session.get("user_id"), order_id)
    if status == "not_found":
        flash("Không tìm thấy đơn hàng để chuyển sang đang giao hàng.", "error")
    elif status == "cancelled":
        flash("Đơn hàng này đã bị hủy trước đó.", "warning")
    elif status == "refund_pending":
        flash("Đơn hàng này đang ở trạng thái Chờ hoàn tiền.", "warning")
    elif status == "completed":
        flash("Đơn hàng đã ở trạng thái hoàn thành.", "warning")
    elif status == "cancel_request_pending":
        flash("Đơn hàng đang có yêu cầu hủy chờ admin duyệt.", "warning")
    elif status == "shipping" and order:
        restaurant_name = session.get("user_display_name") or session.get("username") or "Nhà hàng"
        notification_data = build_order_shipping_notification(order, restaurant_name=restaurant_name)
        emit_structured_notification(notification_data)
        flash(f"Đã chuyển đơn #{order.order_id} sang trạng thái Đang giao hàng.", "success")
    else:
        flash("Không thể chuyển đơn sang trạng thái đang giao hàng lúc này.", "error")

    return redirect(
        url_for(
            "restaurant.orders",
            q=request.values.get("q", ""),
            status=request.values.get("status", "all"),
            sort=request.values.get("sort", "desc"),
            start=request.values.get("start", ""),
            end=request.values.get("end", ""),
            focus=request.values.get("focus", ""),
            page=request.values.get("page", 1),
        )
    )


@bp.route("/orders/<int:order_id>/request-cancel", methods=["POST"])
def request_cancel_order(order_id):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    reason = (request.form.get("reason") or request.args.get("reason") or "").strip()
    order, status, resolved_reason = request_cancel_order_for_restaurant(session.get("user_id"), order_id, reason=reason)
    if not order:
        flash("Không tìm thấy đơn hàng để gửi yêu cầu hủy.", "error")
    elif status == "already_requested":
        flash(f"Đơn #{order.order_id} đã có yêu cầu hủy đang chờ duyệt.", "warning")
    elif status == "already_cancelled":
        flash(f"Đơn #{order.order_id} đã bị hủy trước đó.", "warning")
    elif status == "already_refund_pending":
        flash(f"Đơn #{order.order_id} đang ở trạng thái Chờ hoàn tiền.", "warning")
    elif status == "already_completed":
        flash(f"Đơn #{order.order_id} đã hoàn thành, không thể gửi yêu cầu hủy.", "warning")
    elif status == "requested" and order:
        flash(f"Đã gửi yêu cầu hủy đơn #{order.order_id} đến admin để duyệt.", "success")
    else:
        flash("Không thể gửi yêu cầu hủy lúc này.", "error")

    return redirect(
        url_for(
            "restaurant.orders",
            q=request.values.get("q", ""),
            status=request.values.get("status", "all"),
            sort=request.values.get("sort", "desc"),
            start=request.values.get("start", ""),
            end=request.values.get("end", ""),
            focus=request.values.get("focus", ""),
            page=request.values.get("page", 1),
        )
    )


@bp.route("/orders/<int:order_id>/withdraw-cancel-request", methods=["POST"])
def withdraw_cancel_request(order_id):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    order, status = withdraw_cancel_request_for_restaurant(session.get("user_id"), order_id)
    if not order:
        flash("Không tìm thấy đơn hàng để rút yêu cầu hủy.", "error")
    elif status == "no_pending_request":
        flash(f"Đơn #{order.order_id} không còn yêu cầu hủy đang chờ duyệt.", "warning")
    elif status == "withdrawn":
        flash(f"Đã rút yêu cầu hủy đơn #{order.order_id}.", "success")
    else:
        flash("Không thể rút yêu cầu hủy lúc này.", "error")

    return redirect(
        url_for(
            "restaurant.orders",
            q=request.values.get("q", ""),
            status=request.values.get("status", "all"),
            sort=request.values.get("sort", "desc"),
            start=request.values.get("start", ""),
            end=request.values.get("end", ""),
            focus=request.values.get("focus", ""),
            page=request.values.get("page", 1),
        )
    )


@bp.route("/orders/<int:order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    reason = (request.form.get("reason") or request.args.get("reason") or "").strip()
    order, status, resolved_reason = cancel_order_for_restaurant(session.get("user_id"), order_id, reason=reason)
    if not order:
        flash("Không tìm thấy đơn hàng để hủy.", "error")
    elif status == "already_cancelled":
        flash(f"Đơn #{order.order_id} đã bị hủy trước đó.", "warning")
    elif status == "already_refund_pending":
        flash(f"Đơn #{order.order_id} đang ở trạng thái Chờ hoàn tiền.", "warning")
    else:
        restaurant_name = session.get("user_display_name") or session.get("username") or "Nhà hàng"
        notification_data = build_order_cancelled_notification(order, cancel_reason=resolved_reason, restaurant_name=restaurant_name)
        emit_structured_notification(notification_data)
        if status in {"refund_pending", "pending_refund"}:
            flash(f"Đã chuyển đơn #{order.order_id} sang trạng thái Chờ hoàn tiền.", "success")
        else:
            flash(f"Đã hủy đơn #{order.order_id}.", "success")

    return redirect(
        url_for(
            "restaurant.orders",
            q=request.values.get("q", ""),
            status=request.values.get("status", "all"),
            sort=request.values.get("sort", "desc"),
            start=request.values.get("start", ""),
            end=request.values.get("end", ""),
            focus=request.values.get("focus", ""),
            page=request.values.get("page", 1),
        )
    )


@bp.route("/analytics")
def analytics():
    return _render_section("analytics")


@bp.route("/vouchers", methods=["GET", "POST"])
def vouchers():
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    user_id = session.get("user_id")
    edit_voucher_id = request.args.get("edit", type=int)
    search_query = request.args.get("q", "").strip()
    current_page = request.args.get("page", default=1, type=int)

    if request.method == "POST":
        search_query = (request.form.get("q") or search_query).strip()
        current_page = request.form.get("page", current_page, type=int)
        try:
            voucher, action = save_voucher_for_restaurant(user_id, request.form)
        except ValueError as exc:
            form_errors = exc.args[0] if exc.args else {}
            form_values = dict(request.form)
            if not form_values.get("status"):
                form_values["status"] = ""
            if form_values.get("voucher_id"):
                edit_voucher_id = int(form_values["voucher_id"])
            context = build_section_context(
                user_id,
                "vouchers",
                edit_voucher_id=edit_voucher_id,
                form_values=form_values,
                form_errors=form_errors,
                query=search_query,
                page=current_page,
            )
            return render_template(
                "restaurant/restaurant_voucher_manage.html",
                show_search=False,
                show_auth=False,
                **context,
            )

        flash(f"Đã {action} voucher \"{voucher.voucher_code}\".", "success")
        redirect_page = 1 if action == "created" else current_page
        return redirect(url_for("restaurant.vouchers", q=search_query, page=redirect_page))

    context = build_section_context(
        user_id,
        "vouchers",
        edit_voucher_id=edit_voucher_id,
        query=search_query,
        page=current_page,
    )
    if context["restaurant"] is None:
        flash("Vui lòng hoàn thiện thông tin nhà hàng trước khi quản lý voucher.", "warning")
        return redirect(url_for("auth.complete_restaurant"))

    return render_template(
        "restaurant/restaurant_voucher_manage.html",
        show_search=False,
        show_auth=False,
        **context,
    )


@bp.route("/reviews")
def reviews():
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    context = build_section_context(
        session.get("user_id"),
        "reviews",
        query=request.args.get("q", "").strip(),
        date_from=request.args.get("date_from", "").strip(),
        date_to=request.args.get("date_to", "").strip(),
        review_sentiment=request.args.get("sentiment", "all").strip() or "all",
        review_rating=request.args.get("rating", "all").strip() or "all",
        page=request.args.get("page", default=1, type=int),
    )
    if context["restaurant"] is None:
        flash("Vui lòng hoàn thiện thông tin nhà hàng trước khi xem đánh giá.", "warning")
        return redirect(url_for("auth.complete_restaurant"))

    return render_template(
        "restaurant/restaurant_review_list.html",
        show_search=False,
        show_auth=False,
        **context,
    )


@bp.route("/reviews/ai-insights", methods=["POST"])
def review_ai_insights():
    if not _require_restaurant():
        return jsonify({"ok": False, "message": "Vui lòng đăng nhập với tài khoản nhà hàng."}), 401

    restaurant = get_restaurant_by_user_id(session.get("user_id"))
    if restaurant is None:
        return jsonify({"ok": False, "message": "Không tìm thấy nhà hàng."}), 404

    settings = get_ai_review_summary_settings()
    if not settings["enabled"]:
        return jsonify({"ok": False, "message": "Tính năng AI hiện chưa được cấu hình đầy đủ."}), 503

    negative_reviews = query_negative_reviews_for_improvement_insights(
        restaurant.restaurant_id,
        settings["max_reviews"],
    )
    if len(negative_reviews) < settings["min_reviews"]:
        return jsonify(
            {
                "ok": False,
                "message": f"Cần ít nhất {settings['min_reviews']} đánh giá xấu trong tháng này để tạo gợi ý AI.",
                "threshold": settings["min_reviews"],
            }
        ), 400

    restaurant_name = (
        (restaurant.user.display_name if restaurant.user and restaurant.user.display_name else "")
        or (restaurant.user.username if restaurant.user and restaurant.user.username else "")
        or f"Nhà hàng {restaurant.restaurant_id}"
    )

    try:
        payload = generate_restaurant_review_improvement_insights(
            restaurant.restaurant_id,
            restaurant_name=restaurant_name,
        )
    except ReviewSummaryConfigError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 503
    except ReviewSummaryRequestError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 503

    return jsonify({"ok": True, **payload})


@bp.route("/reviews/<int:review_id>/report", methods=["POST"])
def report_review(review_id):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    reason = (request.form.get("reason") or "").strip()
    review, status = report_review_for_restaurant(session.get("user_id"), review_id, reason=reason)

    if status == "restaurant_not_found":
        flash("Vui lòng hoàn thiện thông tin nhà hàng trước khi báo cáo đánh giá.", "warning")
        return redirect(url_for("auth.complete_restaurant"))
    if status == "review_not_found":
        flash("Không tìm thấy đánh giá để báo cáo hoặc đánh giá không thuộc nhà hàng của bạn.", "error")
    elif status == "already_reported":
        flash("Đánh giá này đã được báo cáo và đang chờ admin xử lý.", "warning")
    elif status == "reported" and review:
        flash("Đã gửi báo cáo đánh giá cho admin xem xét.", "success")
    else:
        flash("Không thể báo cáo đánh giá lúc này.", "error")

    return redirect(url_for("restaurant.reviews"))


@bp.route("/dishes/<int:dish_id>/toggle", methods=["POST"])
def toggle_dish(dish_id):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    dish = toggle_dish_status_for_restaurant(session.get("user_id"), dish_id)
    redirect_args = {
        "q": request.args.get("q", ""),
        "category": request.args.get("category", "all"),
        "page": request.args.get("page", 1, type=int),
    }
    if not dish:
        flash("Không tìm thấy món ăn để thay đổi trạng thái.", "error")
    else:
        flash(
            f"Đã chuyển trạng thái món \"{dish.dish_name}\" sang {'còn' if dish.status else 'hết' }.",
            "success",
        )
    return redirect(url_for("restaurant.dashboard", **redirect_args))


@bp.route("/vouchers/<int:voucher_id>/toggle", methods=["POST"])
def toggle_voucher(voucher_id):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    voucher = toggle_voucher_status_for_restaurant(session.get("user_id"), voucher_id)
    redirect_args = {
        "q": request.args.get("q", ""),
        "page": request.args.get("page", 1, type=int),
    }
    if not voucher:
        flash("Không tìm thấy voucher để thay đổi trạng thái.", "error")
    else:
        flash(
            f"Đã chuyển trạng thái voucher \"{voucher.voucher_code}\" sang {'bật' if voucher.status else 'tắt' }.",
            "success",
        )
    return redirect(url_for("restaurant.vouchers", **redirect_args))


@bp.route("/dishes/<int:dish_id>/delete", methods=["POST"])
def delete_dish(dish_id):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    deleted = delete_dish_for_restaurant(session.get("user_id"), dish_id)
    redirect_args = {
        "q": request.args.get("q", ""),
        "category": request.args.get("category", "all"),
        "page": request.args.get("page", 1, type=int),
    }
    if not deleted:
        flash("Không thể xoá món vì món không tồn tại hoặc không thuộc nhà hàng của bạn.", "error")
    else:
        flash("Đã xoá món ăn khỏi thực đơn.", "success")
    return redirect(url_for("restaurant.dashboard", **redirect_args))


@bp.route("/vouchers/<int:voucher_id>/delete", methods=["POST"])
def delete_voucher(voucher_id):
    if not _require_restaurant():
        return redirect(url_for("home.index"))

    deleted = delete_voucher_for_restaurant(session.get("user_id"), voucher_id)
    redirect_args = {
        "q": request.args.get("q", ""),
        "page": request.args.get("page", 1, type=int),
    }
    if not deleted:
        flash("Không thể xoá voucher vì voucher không tồn tại hoặc đã được dùng trong đơn hàng.", "error")
    else:
        flash("Đã xoá voucher khỏi hệ thống.", "success")
    return redirect(url_for("restaurant.vouchers", **redirect_args))
