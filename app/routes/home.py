from flask import Blueprint, render_template, request

from app.services.home_service import get_home_page_context

bp = Blueprint("home", __name__)


@bp.route("/")
def index():
    query = request.args.get("q", "").strip()
    page = get_home_page_context(query)
    return render_template("home.html", page=page)
