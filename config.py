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


def _env(*names, default=""):
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")
    AI_REVIEW_SUMMARY_MIN_REVIEWS = int(os.getenv("AI_REVIEW_SUMMARY_MIN_REVIEWS", "5"))
    AI_REVIEW_SUMMARY_MAX_REVIEWS = int(os.getenv("AI_REVIEW_SUMMARY_MAX_REVIEWS", "30"))
    AI_REVIEW_SUMMARY_TIMEOUT_SECONDS = float(os.getenv("AI_REVIEW_SUMMARY_TIMEOUT_SECONDS", "15"))
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
    GOOGLE_CLIENT_ID = _env("GOOGLE_CLIENT_ID", "GOOGLE_CUSTOMER_ID", "GOOGLE_OAUTH_CLIENT_ID", default="")
    GOOGLE_CLIENT_SECRET = _env("GOOGLE_CLIENT_SECRET", "GOOGLE_CUSTOMER_SECRET", "GOOGLE_OAUTH_CLIENT_SECRET", default="")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5000/callback")
    GOOGLE_AUTH_URL = os.getenv("GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
    GOOGLE_TOKEN_URL = os.getenv("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")
    GOOGLE_USERINFO_URL = os.getenv("GOOGLE_USERINFO_URL", "https://www.googleapis.com/oauth2/v3/userinfo")
