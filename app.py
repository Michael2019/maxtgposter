import csv
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

import requests
from flask import Flask, flash, jsonify, redirect, request, session, url_for
from flask_cors import CORS
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, verify_jwt_in_request

import auth
import config
from blueprints.admin_bp import admin_bp
from blueprints.auth_bp import auth_bp
from blueprints.main_bp import main_bp
from extensions import cache, csrf, jwt
from services.media_files import ensure_telegram_friendly_videos, prepare_files_for_publish
from services.publish_max import send_to_max as max_send_message
from services.publish_telegram import send_to_telegram
from services.publish_queue import create_job, get_job, run_job_async
from forms.post_constants import COMPENSATORY_CATEGORY

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN")
SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")
_templates_http = requests.Session()

# Кэш CSV шаблонов из Google Sheets — снижает задержку перед постановкой в очередь
_TEMPLATE_CSV_CACHE = {"rows": None, "fetched_at": 0.0}
_TEMPLATE_CSV_TTL_SEC = float(os.environ.get("TEMPLATE_CSV_TTL_SEC", "1800"))


def _find_template_text(rows, category, module, lesson):
    cat = str(category).strip()
    mod = str(module).strip()
    les = str(lesson).strip()
    for row in rows:
        if (
            str(row.get("category", "")).strip() == cat
            and str(row.get("module", "")).strip() == mod
            and str(row.get("lesson", "")).strip() == les
        ):
            text = (row.get("post_text") or "").strip()
            if text:
                return text
    return None


def get_post_template(category, module, lesson):
    if str(category).strip() == COMPENSATORY_CATEGORY:
        return COMPENSATORY_CATEGORY
    fallback = f"{category}, модуль {module}, занятие {lesson}"
    try:
        from flask import has_app_context

        if has_app_context():
            from services.sheets import sheets_service

            rows = sheets_service.get_templates()
            found = _find_template_text(rows, category, module, lesson)
            if found:
                return found
    except Exception as e:
        print(f"Ошибка шаблона (Sheets): {e}")

    try:
        if not SHEETS_CSV_URL:
            return fallback
        now = time.monotonic()
        rows = _TEMPLATE_CSV_CACHE["rows"]
        if rows is None or (now - _TEMPLATE_CSV_CACHE["fetched_at"]) > _TEMPLATE_CSV_TTL_SEC:
            response = _templates_http.get(SHEETS_CSV_URL, timeout=10)
            response.raise_for_status()
            csv_data = response.content.decode("utf-8")
            reader = csv.DictReader(StringIO(csv_data))
            rows = list(reader)
            _TEMPLATE_CSV_CACHE["rows"] = rows
            _TEMPLATE_CSV_CACHE["fetched_at"] = now
        found = _find_template_text(rows, category, module, lesson)
        return found if found else fallback
    except Exception as e:
        print(f"Ошибка шаблона (CSV): {e}")
        return fallback


def clear_template_csv_cache():
    _TEMPLATE_CSV_CACHE["rows"] = None
    _TEMPLATE_CSV_CACHE["fetched_at"] = 0.0

def trim_text_to_limit(main_text, signature, max_length):
    full = main_text + signature
    if len(full) <= max_length:
        return full
    paragraphs = main_text.split('\n\n')
    while paragraphs and len('\n\n'.join(paragraphs) + signature) > max_length:
        paragraphs.pop()
    trimmed_main = '\n\n'.join(paragraphs)
    if len(trimmed_main + signature) > max_length:
        if len(signature) > max_length:
            signature = signature[:max_length - 3] + '...'
        return signature
    return trimmed_main + signature


def split_text_chunks(text, chunk_size):
    text = text or ""
    if not text:
        return []
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


def build_post_text_payload(form_data, role):
    override = (form_data.get("preview_final_text") or "").strip()
    if override:
        return override[:4096] if len(override) > 4096 else override

    user_text = form_data.get('user_text', '').strip()
    category = form_data.get('category', '')
    module = form_data.get('module', '')
    lesson = form_data.get('lesson', '')
    weekday = form_data.get('weekday', '')
    time_val = form_data.get('time', '')
    form_type = form_data.get('form_type', 'lessons')

    if str(category).strip() == COMPENSATORY_CATEGORY:
        tags = []
        if weekday and time_val:
            tags.append(f"#{weekday.lower()}_{time_val.replace(':', '_')}")
        if category:
            tags.append(f"#{re.sub(r'[^\w\s-]', '', category).replace(' ', '_')}")
        # Для компенсирующего занятия публикуем только хэштеги.
        return " ".join(tags).strip()

    if form_type == "camp":
        base_text = user_text if user_text else ""
    elif user_text:
        base_text = user_text
    else:
        base_text = get_post_template(category, module, lesson)

    tags = []
    if weekday and time_val:
        tags.append(f"#{weekday.lower()}_{time_val.replace(':', '_')}")
    if category:
        tags.append(f"#{re.sub(r'[^\w\s-]', '', category).replace(' ', '_')}")

    full_text = f"{' '.join(tags)}\n{base_text}" if tags else base_text
    signature = ""
    role = str(role or "").strip()
    if role and role.lower() not in ("admin", "user", "moderator"):
        signature = f"\n\nВаш наставник {role}" if form_type == "camp" else f"\n\nВаш преподаватель {role}"
    return trim_text_to_limit(full_text, signature, 4096)


def _resolve_user():
    try:
        verify_jwt_in_request()
        claims = get_jwt()
        return get_jwt_identity(), claims.get("role", "")
    except Exception:
        user = session.get("user") or {}
        return user.get("username"), user.get("role", "")


def create_app():
    app = Flask(__name__)
    CORS(app, origins="*", allow_headers=["Authorization", "Content-Type"])
    app.config.from_object(config.Config)
    app.secret_key = app.config["SECRET_KEY"]

    cache.init_app(app)
    jwt.init_app(app)
    csrf.init_app(app)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @jwt.unauthorized_loader
    def unauthorized_callback(reason):
        return jsonify({"error": "Missing or invalid token", "ok": False}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(reason):
        return jsonify({"error": "Invalid token", "ok": False}), 422

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({"error": "Token expired", "ok": False}), 401

    @app.route("/api/login", methods=["POST"])
    @csrf.exempt
    def login_api():
        data = request.get_json() or {}
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return jsonify({"error": "Логин и пароль обязательны", "ok": False}), 400
        user = auth.authenticate_user(username, password)
        if not user:
            return jsonify({"error": "Неверный логин или пароль", "ok": False}), 401
        access_token = create_access_token(
            identity=user.get("username"),
            additional_claims={"username": user.get("username"), "role": user.get("role", "")},
        )
        return jsonify({"ok": True, "access_token": access_token, "user": user}), 200

    @app.route("/api/me", methods=["GET"])
    def me():
        verify_jwt_in_request()
        current_username = get_jwt_identity()
        claims = get_jwt()
        return jsonify({"ok": True, "user": {"username": current_username, "role": claims.get("role", "")}}), 200

    @app.route("/post", methods=["POST"])
    @csrf.exempt
    def create_post():
        wants_json = request.path.startswith("/api/") or request.is_json or request.headers.get("Accept", "").startswith("application/json")

        def _form_redirect_with_flash():
            target = "main.camp_page" if request.form.get("form_type") == "camp" else "main.test_page"
            return redirect(url_for(target))

        try:
            app.logger.info("POST /post: request received")
            current_username, role = _resolve_user()
            if not current_username:
                app.logger.warning("POST /post: unauthorized request")
                if wants_json:
                    return jsonify({"error": "Требуется авторизация", "ok": False}), 401
                flash("Требуется авторизация", "danger")
                return redirect(url_for("auth.login"))
            role = str(role).strip()
            app.logger.info("POST /post: user=%s role=%s", current_username, role)

            # Основные поля
            user_text = request.form.get('user_text', '').strip()
            category = request.form.get('category', '')
            module = request.form.get('module', '')
            lesson = request.form.get('lesson', '')
            weekday = request.form.get('weekday', '')
            time_val = request.form.get('time', '')
            telegram_chat_id = request.form.get('chat_id', '')
            max_chat_id = request.form.get('max_chat_id', '')
            channel = request.form.get("channel", "").strip()
            uploaded_files = request.files.getlist('media_files')
            form_type = request.form.get('form_type', 'lessons')
            app.logger.info(
                "POST /post: form parsed form_type=%s chat_id=%s max_chat_id=%s files=%s user_text_len=%s category=%r module=%r lesson=%r weekday=%r time=%r",
                form_type,
                telegram_chat_id,
                max_chat_id,
                len(uploaded_files),
                len(user_text),
                category,
                module,
                lesson,
                weekday,
                time_val,
            )

            max_files = int(os.environ.get("POST_MAX_MEDIA_FILES", "5"))
            files_data = []
            for f in uploaded_files:
                if not f or not getattr(f, "filename", None):
                    continue
                if len(files_data) >= max_files:
                    msg = f"Можно прикрепить не более {max_files} файлов"
                    if wants_json:
                        return jsonify({"error": msg, "ok": False}), 400
                    flash(msg, "danger")
                    return _form_redirect_with_flash()
                content = f.read()
                if not content:
                    continue
                max_mb = float(os.environ.get("TELEGRAM_MAX_UPLOAD_MB", "48"))
                if len(content) > int(max_mb * 1024 * 1024):
                    msg = f"Файл {f.filename} слишком большой (лимит {int(max_mb)} МБ)"
                    if wants_json:
                        return jsonify({"error": msg, "ok": False}), 400
                    flash(msg, "danger")
                    return _form_redirect_with_flash()
                files_data.append((f.filename, content, f.mimetype))
                app.logger.info(
                    "POST /post: file loaded name=%s size=%s mime=%s",
                    f.filename,
                    len(content),
                    f.mimetype,
                )
            uploads_before_prepare = len(files_data)
            files_data = prepare_files_for_publish(files_data)

            if not telegram_chat_id:
                app.logger.warning("POST /post: missing telegram chat_id")
                if wants_json:
                    return jsonify({"error": "Не указан ID канала Telegram", "ok": False}), 400
                flash("Не указан ID канала Telegram", "danger")
                return _form_redirect_with_flash()

            final_text = build_post_text_payload(request.form, role)
            app.logger.info("POST /post: final_text_len=%s", len(final_text))

            if uploads_before_prepare > 0 and not files_data:
                msg = "Вложения не приняты: файл пустой, слишком большой или неподдерживаемый формат"
                if wants_json:
                    return jsonify({"error": msg, "ok": False}), 400
                flash(msg, "danger")
                return _form_redirect_with_flash()

            if not (final_text or "").strip() and not files_data:
                msg = "Добавьте текст поста или вложения"
                app.logger.warning("POST /post: empty text and no files")
                if wants_json:
                    return jsonify({"error": msg, "ok": False}), 400
                flash(msg, "danger")
                return _form_redirect_with_flash()

            payload = {
                "telegram_chat_id": telegram_chat_id,
                "max_chat_id": max_chat_id,
                "channel": channel or telegram_chat_id or max_chat_id,
                "text": final_text,
                "files_data": files_data,
            }
            job_id = create_job(payload, {"username": current_username, "role": role})

            def _publish():
                files_for_send = ensure_telegram_friendly_videos(payload["files_data"])

                def _run_telegram():
                    return send_to_telegram(payload["telegram_chat_id"], payload["text"], files_for_send)

                def _run_max():
                    if payload["max_chat_id"] and MAX_BOT_TOKEN:
                        return max_send_message(
                            payload["max_chat_id"],
                            payload["text"],
                            files_for_send,
                            MAX_BOT_TOKEN,
                        )
                    return {"ok": False, "skipped": True}

                with ThreadPoolExecutor(max_workers=2) as pool:
                    fut_tg = pool.submit(_run_telegram)
                    fut_mx = pool.submit(_run_max)
                    tg_result = fut_tg.result()
                    max_result = fut_mx.result()
                tg_ok = bool(tg_result.get("ok"))
                max_ok = bool(max_result.get("ok") or max_result.get("skipped"))
                if not tg_ok or not max_ok:
                    parts = []
                    if not tg_ok:
                        parts.append(f"Telegram: {tg_result.get('error') or tg_result.get('description') or 'ошибка'}")
                    if not max_ok:
                        parts.append(f"MAX: {max_result.get('error') or 'ошибка'}")
                    raise RuntimeError("; ".join(parts))
                return {"ok": True, "telegram": tg_result, "max": max_result}

            run_job_async(job_id, _publish)

            if wants_json:
                return jsonify({"ok": True, "queued": True, "job_id": job_id}), 202

            flash(
                f"Публикация в очереди (ID {job_id[:8]}). Если пост не появился — смотрите «История» в админке.",
                "info",
            )
            return _form_redirect_with_flash()
        except Exception as e:
            app.logger.exception("POST /post: unhandled error: %s", e)
            if wants_json:
                return jsonify({"error": str(e), "ok": False}), 500
            flash(f"Ошибка публикации: {e}", "danger")
            return _form_redirect_with_flash()

    @app.route("/api/preview", methods=["POST"])
    @csrf.exempt
    def preview_post():
        try:
            current_username, role = _resolve_user()
            if not current_username:
                return jsonify({"ok": False, "error": "Требуется авторизация"}), 401
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                return jsonify({"ok": False, "error": "Некорректные данные предпросмотра"}), 400
            text = build_post_text_payload(payload, role)
            return jsonify({"ok": True, "preview_text": text, "length": len(text)}), 200
        except Exception as e:
            app.logger.exception("POST /api/preview: unhandled error: %s", e)
            return jsonify({"ok": False, "error": f"Ошибка предпросмотра: {e}"}), 500

    @app.route("/api/jobs/<job_id>", methods=["GET"])
    @csrf.exempt
    def get_job_status(job_id):
        job = get_job(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Job not found"}), 404
        return jsonify({"ok": True, "job": job}), 200

    from services.cache_helpers import register_template_change_hook

    register_template_change_hook(clear_template_csv_cache)

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception("Unhandled server error: %s", error)
        wants_json = request.path.startswith("/api/") or request.is_json or request.headers.get("Accept", "").startswith("application/json")
        if wants_json:
            return jsonify({"ok": False, "error": "Внутренняя ошибка сервера"}), 500
        flash("Внутренняя ошибка сервера", "danger")
        return redirect(url_for("admin.dashboard"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
