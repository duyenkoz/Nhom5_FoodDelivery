import importlib

from flask import Flask

from app.commands import register_commands
from config import Config
from app.extensions import db, login_manager, mail, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)

    # Import models so Flask-Migrate/SQLAlchemy can register tables.
    importlib.import_module("app.models")
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.routes.auth import bp as auth_bp
    from app.routes.home import bp as home_bp
    from app.routes.location import bp as location_bp
    from app.routes.password_reset import bp as password_reset_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(location_bp)
    app.register_blueprint(password_reset_bp)
    register_commands(app)

    return app
