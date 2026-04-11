from flask import Blueprint, jsonify, request

from app.services.location_service import resolve_address, search_addresses


bp = Blueprint("location", __name__, url_prefix="/location")


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


@bp.route("/search")
def search():
    query = _clean(request.args.get("q"))
    selected_area = _clean(request.args.get("area"))
    results = search_addresses(query, selected_area=selected_area, limit=8)
    return jsonify({"results": results})


@bp.route("/resolve")
def resolve():
    query = _clean(request.args.get("q"))
    selected_area = _clean(request.args.get("area"))
    location = resolve_address(query, selected_area=selected_area, require_area_match=bool(selected_area))

    if not location:
        return jsonify({"ok": False, "message": "Không tìm thấy địa chỉ phù hợp."}), 404

    return jsonify({"ok": True, "location": location})
