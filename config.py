import os

from dotenv import load_dotenv
from sqlalchemy.engine import URL


load_dotenv()


def _build_database_uri():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    return URL.create(
        drivername=os.getenv("DB_DRIVER", "mysql+pymysql"),
        username=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", "admin@123"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME", "food_delivery"),
    ).render_as_string(hide_password=False)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    TRACK_ASIA_MAPS_API_KEY = os.getenv("TRACK_ASIA_MAPS_API_KEY", "")
    TRACK_ASIA_BASE_URL = os.getenv("TRACK_ASIA_BASE_URL", "https://maps.track-asia.com/api/v2/place")
    TRACK_ASIA_TIMEOUT_SECONDS = float(os.getenv("TRACK_ASIA_TIMEOUT_SECONDS", "6"))
    TRACK_ASIA_USE_NEW_ADMIN = os.getenv("TRACK_ASIA_USE_NEW_ADMIN", "true").lower() in {"1", "true", "yes", "on"}
    NOMINATIM_BASE_URL = os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")
    NOMINATIM_USER_AGENT = os.getenv("NOMINATIM_USER_AGENT", "fiveFood/1.0")
    NOMINATIM_TIMEOUT_SECONDS = float(os.getenv("NOMINATIM_TIMEOUT_SECONDS", "6"))
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "false").lower() in {"1", "true", "yes", "on"}
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "ngocnhu6212@gmail.com")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
