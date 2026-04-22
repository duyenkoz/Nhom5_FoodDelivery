from flask import session
from flask_socketio import emit, join_room

from app.extensions import socketio


@socketio.on("connect")
def handle_connect():
    if session.get("auth_state") != "logged_in":
        return False

    user_id = session.get("user_id")
    if not user_id:
        return False

    join_room(f"user_{user_id}")
    emit(
        "notification:connected",
        {
            "user_id": user_id,
            "user_role": session.get("user_role") or "",
        },
    )
