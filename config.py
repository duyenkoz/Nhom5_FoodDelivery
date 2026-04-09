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
