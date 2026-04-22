from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO


db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
mail = Mail()
socketio = SocketIO(async_mode="threading", manage_session=False)

