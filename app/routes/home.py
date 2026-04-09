from flask import Blueprint, render_template, request

from app.services.home_service import get_home_page_context

bp = Blueprint("home", __name__)


@bp.route("/")
def index():
    query = request.args.get("q", "").strip()
    page_number = request.args.get("page", default=1, type=int)
    page = get_home_page_context(query, page_number)
    return render_template("home.html", page=page)
