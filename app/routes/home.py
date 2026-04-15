from flask import Blueprint, abort, jsonify, make_response, render_template, request, session
from flask import redirect, url_for

from app.extensions import db
from app.models.customer import Customer
from app.services.auth_service import is_customer_profile_complete
from app.services.home_search_service import build_hot_search_keywords, build_search_suggestions, get_home_page_context
from app.services.home_service import get_restaurant_collection_context
from app.services.location_service import resolve_address
from app.services.public_restaurant_service import (
    add_to_restaurant_cart,
    build_public_restaurant_context,
    get_restaurant_cart_snapshot,
    update_restaurant_cart_item,
)

bp = Blueprint("home", __name__)


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _parse_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_user_location():
    user_id = session.get("user_id")
    address = _clean(request.args.get("address"))
    area = _clean(request.args.get("area"))
    latitude = _parse_float(request.args.get("lat"))
    longitude = _parse_float(request.args.get("lon"))

    if address and latitude is not None and longitude is not None:
        return {
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
            "area": area,
            "source": "query",
        }

    if user_id and session.get("user_role") == "customer":

        try:
            customer_id = int(user_id)
        except (TypeError, ValueError):
            customer_id = None

        customer = db.session.get(Customer, customer_id) if customer_id is not None else None
        if customer:
            if customer.latitude is not None and customer.longitude is not None:
                return {
                    "address": customer.address or "",
                    "latitude": customer.latitude,
                    "longitude": customer.longitude,
                    "area": customer.area or "",
                    "source": "customer",
                }

            if customer.address:
                resolved = resolve_address(customer.address, selected_area=customer.area, require_area_match=False)
                if resolved:
                    return {
                        "address": customer.address or resolved["display_name"],
                        "latitude": resolved["lat"],
                        "longitude": resolved["lon"],
                        "area": customer.area or resolved.get("area", ""),
                        "source": "customer-resolved",
                    }

    return None


def _get_location_storage_key():
    if session.get("auth_state") == "logged_in" and session.get("user_role") == "customer" and session.get("user_id"):
        return f"fivefood:location:customer:{session.get('user_id')}"
    return "fivefood:location:anonymous"


def _remember_search_query(query):
    query = _clean(query)
    if not query:
        return

    recent_searches = session.get("fivefood_recent_searches", [])
    if not isinstance(recent_searches, list):
        recent_searches = []

    recent_searches = [item for item in recent_searches if item != query]
    recent_searches.insert(0, query)
    session["fivefood_recent_searches"] = recent_searches[:5]
    session.modified = True


@bp.route("/")
def index():
    if session.get("auth_state") == "logged_in" and session.get("user_role") == "customer" and not is_customer_profile_complete(session.get("user_id")):
        return redirect(url_for("auth.complete_customer"))

    query = request.args.get("q", "").strip()
    if query:
        _remember_search_query(query)
    tab = request.args.get("tab", "all").strip().lower()
    page_number = request.args.get("page", default=1, type=int)
    user_location = _get_user_location()
    hero_address = user_location["address"] if user_location else ""
    page = get_home_page_context(query, page_number, user_location=user_location, hero_address=hero_address, tab=tab)
    page["location_storage_key"] = _get_location_storage_key()
    page["location_persist"] = True
    clear_location_cookie = request.cookies.get("fivefood_clear_location") == "1"
    if clear_location_cookie:
        page["location_clear_storage_key"] = "fivefood:location:anonymous"
    response = make_response(render_template("home_search.html", page=page))
    if clear_location_cookie:
        response.delete_cookie("fivefood_clear_location")
    return response


@bp.route("/collections/<section_key>")
def restaurant_collection(section_key):
    user_location = _get_user_location()
    hero_address = user_location["address"] if user_location else ""
    page_number = request.args.get("page", default=1, type=int)
    page = get_restaurant_collection_context(
        section_key,
        page_number=page_number,
        user_location=user_location,
        hero_address=hero_address,
    )
    if page is None:
        abort(404)

    page["location_storage_key"] = _get_location_storage_key()
    page["location_persist"] = True
    clear_location_cookie = request.cookies.get("fivefood_clear_location") == "1"
    if clear_location_cookie:
        page["location_clear_storage_key"] = "fivefood:location:anonymous"

    response = make_response(render_template("restaurant_collection.html", page=page))
    if clear_location_cookie:
        response.delete_cookie("fivefood_clear_location")
    return response


@bp.route("/collections/<section_key>/load-more")
def restaurant_collection_load_more(section_key):
    user_location = _get_user_location()
    hero_address = user_location["address"] if user_location else ""
    page_number = request.args.get("page", default=1, type=int)
    page = get_restaurant_collection_context(
        section_key,
        page_number=page_number,
        user_location=user_location,
        hero_address=hero_address,
    )
    if page is None:
        abort(404)

    html = render_template("partials/home_card_items.html", items=page["items"])
    return jsonify(
        {
            "ok": True,
            "html": html,
            "has_more": page["has_more"],
            "next_page": page["current_page"] + 1 if page["has_more"] else None,
            "load_more_url": page["load_more_url"],
        }
    )


@bp.route("/search-popover")
def search_popover():
    hot_limit = request.args.get("limit", default=10, type=int) or 10
    hot = build_hot_search_keywords(limit=hot_limit, days=7)
    return jsonify({"hot": hot})


@bp.route("/search-suggestions")
def search_suggestions():
    query = request.args.get("q", "").strip()
    limit = request.args.get("limit", default=5, type=int) or 5
    suggestions = build_search_suggestions(query, limit=limit)
    return jsonify({"suggestions": suggestions})


@bp.route("/search-history/clear", methods=["POST"])
def clear_search_history():
    session.pop("fivefood_recent_searches", None)
    session.modified = True
    return jsonify({"ok": True})


def _parse_json_payload():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


@bp.route("/restaurants/<int:restaurant_id>")
def restaurant_detail(restaurant_id):
    context = build_public_restaurant_context(restaurant_id)
    if context is None:
        abort(404)

    context["cart"] = get_restaurant_cart_snapshot(session, restaurant_id)
    return render_template("restaurant_detail.html", page=context)


@bp.route("/restaurants/<int:restaurant_id>/cart")
def restaurant_cart(restaurant_id):
    context = build_public_restaurant_context(restaurant_id)
    if context is None:
        abort(404)
    return jsonify({"ok": True, "cart": get_restaurant_cart_snapshot(session, restaurant_id)})


@bp.route("/restaurants/<int:restaurant_id>/cart/items", methods=["POST"])
def add_restaurant_cart_item(restaurant_id):
    context = build_public_restaurant_context(restaurant_id)
    if context is None:
        abort(404)

    payload = _parse_json_payload()
    dish_id = payload.get("dish_id")
    quantity = payload.get("quantity", 1)
    note = payload.get("note", "")

    try:
        dish_id = int(dish_id)
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Dữ liệu món ăn không hợp lệ."}), 400

    cart = add_to_restaurant_cart(session, restaurant_id, dish_id, quantity=quantity, note=note)
    if cart is None:
        return jsonify({"ok": False, "message": "Không tìm thấy món ăn hợp lệ."}), 404

    return jsonify({"ok": True, "cart": cart})


@bp.route("/restaurants/<int:restaurant_id>/cart/items/<int:dish_id>", methods=["POST"])
def update_restaurant_cart(restaurant_id, dish_id):
    context = build_public_restaurant_context(restaurant_id)
    if context is None:
        abort(404)

    payload = _parse_json_payload()
    quantity = payload.get("quantity")
    note = payload.get("note") if "note" in payload else None

    try:
        if quantity is not None:
            quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Số lượng không hợp lệ."}), 400

    cart = update_restaurant_cart_item(session, restaurant_id, dish_id, quantity=quantity, note=note)
    if cart is None:
        return jsonify({"ok": False, "message": "Không tìm thấy món ăn hợp lệ."}), 404

    return jsonify({"ok": True, "cart": cart})
