import importlib

from flask import Flask, session

from app.commands import register_commands
from app.extensions import db, login_manager, mail, migrate, socketio
from app.services.notification_service import get_user_notification_count, get_user_notifications
from app.utils.time_utils import format_vietnam_date, format_vietnam_datetime
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app)

    # Import models so Flask-Migrate/SQLAlchemy can register tables.
    importlib.import_module("app.models")
    from app.models.restaurant import Restaurant
    from app.models.notification import Notification
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_header_account_names():
        if session.get("auth_state") != "logged_in":
            return {}

        user_id = session.get("user_id")
        user = None
        restaurant = None

        try:
            if user_id is not None:
                user = db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            user = None

        if user and user.role == "restaurant":
            restaurant = db.session.get(Restaurant, user.user_id)

        restaurant_display_name = ""
        if user and user.role == "restaurant":
            restaurant_display_name = (
                (user.display_name or "").strip()
                or (restaurant.user.display_name if restaurant and restaurant.user and restaurant.user.display_name else "")
                or (user.username or "").strip()
            )

        resolved_user_id = user.user_id if user else session.get("user_id")
        return {
            "header_user_name": (user.display_name or user.username or "Tài khoản") if user else "Tài khoản",
            "header_user_role": user.role if user else session.get("user_role"),
            "header_restaurant_display_name": restaurant_display_name,
            "header_notifications": get_user_notifications(resolved_user_id, unread_only=False, limit=6),
            "header_notification_count": get_user_notification_count(resolved_user_id),
        }

    @app.template_filter("vn_datetime")
    def vn_datetime_filter(value, fmt="%d/%m/%Y %H:%M"):
        return format_vietnam_datetime(value, fmt)

    @app.template_filter("vn_date")
    def vn_date_filter(value, fmt="%d/%m/%Y"):
        return format_vietnam_date(value, fmt)

    from app.routes.admin import bp as admin_bp
    from app.routes.auth import bp as auth_bp
    from app.routes.checkout import bp as checkout_bp
    from app.routes.home import bp as home_bp
    from app.routes.location import bp as location_bp
    from app.routes.notifications import bp as notifications_bp
    from app.routes.password_reset import bp as password_reset_bp
    from app.routes.restaurant import bp as restaurant_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(location_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(password_reset_bp)
    app.register_blueprint(restaurant_bp)
    app.register_blueprint(notifications_bp)
    register_commands(app)

    with app.app_context():
        try:
            Notification.__table__.create(bind=db.engine, checkfirst=True)
        except Exception:
            pass

    importlib.import_module("app.realtime")

    return app
