import hashlib
from functools import wraps
from flask import current_app, jsonify, redirect, session, url_for
from flask_jwt_extended import get_jwt, verify_jwt_in_request

from services.sheets import sheets_service


def _normalize_text(value):
    if value is None:
        return ""
    # Remove BOM/zero-width chars and trim spaces/newlines.
    return str(value).replace("\ufeff", "").replace("\u200b", "").strip()


def hash_password(password):
    normalized_password = _normalize_text(password)
    return hashlib.sha256(normalized_password.encode("utf-8")).hexdigest()

SESSION_USER_KEYS = ("username", "role", "family", "email", "is_admin", "row_number", "id")


def user_for_session(user):
    """Убрать чувствительные поля перед записью в cookie-сессию."""
    if not user:
        return {}
    return {k: user[k] for k in SESSION_USER_KEYS if k in user and k != "password_hash"}


def get_users_from_sheets():
    users = sheets_service.get_users()
    current_app.logger.info("Auth: users loaded from storage: count=%s", len(users))
    return users

def authenticate_user(username, password):
    raw_username = username
    username = _normalize_text(username)
    password = _normalize_text(password)
    current_app.logger.info(
        "Auth: login attempt username_raw=%r username_norm=%r password_len=%s",
        raw_username,
        username,
        len(password),
    )

    users = get_users_from_sheets()
    password_hash = hash_password(password)
    current_app.logger.info("Auth: computed password hash prefix=%s", password_hash[:12])

    if not users:
        current_app.logger.warning("Auth: users source returned empty list")

    seen_usernames = []
    for user in users:
        candidate_username = _normalize_text(user.get("username"))
        candidate_hash = _normalize_text(user.get("password_hash")).lower()
        candidate_role = _normalize_text(user.get("role"))
        seen_usernames.append(candidate_username)

        username_match = candidate_username == username
        hash_match = candidate_hash == password_hash
        current_app.logger.info(
            "Auth: compare row=%s username=%r role=%r username_match=%s hash_match=%s candidate_hash_prefix=%s",
            user.get("row_number", "?"),
            candidate_username,
            candidate_role,
            username_match,
            hash_match,
            candidate_hash[:12] if candidate_hash else "",
        )

        if username_match and hash_match:
            current_app.logger.info(
                "Auth: success username=%r row=%s role=%r is_admin=%r",
                candidate_username,
                user.get("row_number", "?"),
                candidate_role,
                user.get("is_admin"),
            )
            return user

    current_app.logger.warning(
        "Auth: failed for username=%r; available_usernames=%r",
        username,
        seen_usernames,
    )
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            verify_jwt_in_request()
            return f(*args, **kwargs)
        except Exception as e:
            print(f"🔒 Ошибка авторизации: {e}")
            return jsonify({"error": "Требуется авторизация", "ok": False}), 401
    return decorated_function


def web_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get("user") or {}
        role = str(user.get("role", "")).lower()
        is_admin = str(user.get("is_admin", "")).lower() in {"true", "1", "yes"}
        if role != "admin" and not is_admin:
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return decorated_function


def jwt_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        verify_jwt_in_request()
        claims = get_jwt()
        role = str(claims.get("role", "")).lower()
        if role != "admin":
            return jsonify({"error": "Admin access required", "ok": False}), 403
        return f(*args, **kwargs)
    return decorated_function
