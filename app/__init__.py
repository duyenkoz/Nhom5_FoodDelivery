import importlib

from flask import Flask

from config import Config
from app.extensions import db, login_manager, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # Import models so Flask-Migrate/SQLAlchemy can register tables.
    importlib.import_module("app.models")
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.routes.main import bp as main_bp

    app.register_blueprint(main_bp)

    return app
