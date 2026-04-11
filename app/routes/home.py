from flask import Blueprint, render_template, request, session
from flask import redirect, url_for

from app.extensions import db
from app.models.customer import Customer
from app.services.home_service import get_home_page_context
from app.services.auth_service import is_customer_profile_complete
from app.services.location_service import resolve_address

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
    if user_id and session.get("user_role") == "customer":
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


@bp.route("/")
def index():
    if session.get("auth_state") == "logged_in" and session.get("user_role") == "customer" and not is_customer_profile_complete(session.get("user_id")):
        return redirect(url_for("auth.complete_customer"))

    query = request.args.get("q", "").strip()
    page_number = request.args.get("page", default=1, type=int)
    user_location = _get_user_location()
    hero_address = user_location["address"] if user_location else ""
    page = get_home_page_context(query, page_number, user_location=user_location, hero_address=hero_address)
    page["location_storage_key"] = _get_location_storage_key()
    page["location_persist"] = session.get("auth_state") == "logged_in" and session.get("user_role") == "customer"
    return render_template("home.html", page=page)
