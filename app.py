import csv
import json
import logging
import os
import re
import time
from io import BytesIO, StringIO

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
from services.publish_queue import create_job, get_job, run_job_async

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN")
TELEGRAM_API_BASE_URL = os.environ.get("TELEGRAM_API_BASE_URL", "https://api.telegram.org")
TELEGRAM_PROXY_URL = os.environ.get("TELEGRAM_PROXY_URL")
TELEGRAM_API_URL = f"{TELEGRAM_API_BASE_URL}/bot{BOT_TOKEN}" if BOT_TOKEN else ""
SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")

def get_post_template(category, module, lesson):
    try:
        if not SHEETS_CSV_URL:
            return f"{category}, модуль {module}, занятие {lesson}"
        response = requests.get(SHEETS_CSV_URL, timeout=10)
        response.raise_for_status()
        csv_data = response.content.decode('utf-8')
        reader = csv.DictReader(StringIO(csv_data))
        for row in reader:
            if (row.get('category', '').strip() == str(category) and
                row.get('module', '').strip() == str(module) and
                row.get('lesson', '').strip() == str(lesson)):
                return row.get('post_text', '').strip()
        return f"{category}, модуль {module}, занятие {lesson}"
    except Exception as e:
        print(f"Ошибка шаблона: {e}")
        return f"{category}, модуль {module}, занятие {lesson}"

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
    user_text = form_data.get('user_text', '').strip()
    category = form_data.get('category', '')
    module = form_data.get('module', '')
    lesson = form_data.get('lesson', '')
    weekday = form_data.get('weekday', '')
    time_val = form_data.get('time', '')
    form_type = form_data.get('form_type', 'lessons')

    if user_text:
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


# ============= ОТПРАВКА В TELEGRAM =============
def send_to_telegram(chat_id, text, files_data):
    logger = logging.getLogger("app")
    telegram_proxies = None
    if TELEGRAM_PROXY_URL:
        telegram_proxies = {"http": TELEGRAM_PROXY_URL, "https": TELEGRAM_PROXY_URL}
        logger.info("Telegram: proxy enabled")

    def tg_post(endpoint, *, data=None, files=None, timeout=(15, 40), retries=2):
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                logger.info("Telegram request endpoint=%s attempt=%s", endpoint, attempt)
                return requests.post(
                    f"{TELEGRAM_API_URL}/{endpoint}",
                    data=data,
                    files=files,
                    timeout=timeout,
                    proxies=telegram_proxies,
                )
            except requests.Timeout as e:
                last_error = e
                logger.warning("Telegram timeout endpoint=%s attempt=%s", endpoint, attempt)
                if attempt < retries:
                    time.sleep(1.2 * attempt)
            except requests.RequestException as e:
                last_error = e
                logger.warning("Telegram request exception endpoint=%s attempt=%s error=%s", endpoint, attempt, e)
                if attempt < retries:
                    time.sleep(1.2 * attempt)
        if isinstance(last_error, requests.Timeout):
            raise requests.Timeout()
        raise requests.RequestException(last_error or "Unknown Telegram request error")

    try:
        print(f"📱 send_to_telegram: chat_id={chat_id}, files={len(files_data)}")
        if files_data:
            full_text = text or ""
            caption_limit = 1024
            caption_text = full_text[:caption_limit] if full_text else ""
            remainder_text = full_text[caption_limit:] if len(full_text) > caption_limit else ""
            remainder_chunks = split_text_chunks(remainder_text, 4096)

            media = []
            attachments = {}
            for idx, (filename, content, mime_type) in enumerate(files_data):
                if 'image' in mime_type:
                    media_type = 'photo'
                elif 'video' in mime_type:
                    media_type = 'video'
                else:
                    print(f" ⚠️ файл {filename} пропущен (неподдерживаемый тип)")
                    continue
                attach_name = f"file{idx}"
                media_item = {
                    'type': media_type,
                    'media': f'attach://{attach_name}'
                }
                if idx == 0 and caption_text:
                    media_item['caption'] = caption_text
                    media_item['parse_mode'] = 'HTML'
                media.append(media_item)
                attachments[attach_name] = (filename, BytesIO(content), mime_type)

            if not media:
                return {"ok": False, "error": "Нет поддерживаемых файлов"}

            if len(media) == 1:
                only_item = media[0]
                only_name = next(iter(attachments))
                fname, stream, mime = attachments[only_name]
                endpoint = "sendPhoto" if only_item["type"] == "photo" else "sendVideo"
                payload = {"chat_id": chat_id, "caption": caption_text or "", "parse_mode": "HTML"}
                files_for_tg = {"photo" if endpoint == "sendPhoto" else "video": (fname, stream, mime)}
                print(f"📤 Telegram: отправка single media ({endpoint})...")
                response = tg_post(endpoint, data=payload, files=files_for_tg, timeout=(15, 45), retries=2)
            else:
                payload = {'chat_id': chat_id, 'media': json.dumps(media[:10])}
                files_for_tg = [(name, (fname, stream, mime)) for name, (fname, stream, mime) in attachments.items()]
                print("📤 Telegram: отправка media group...")
                response = tg_post("sendMediaGroup", data=payload, files=files_for_tg, timeout=(15, 45), retries=2)
            print(f" Telegram response: {response.status_code} - {response.text[:200]}")
            if response.status_code != 200:
                return {"ok": False, "error": response.text}

            # If the text is longer than media caption limit, send the rest in follow-up messages.
            if remainder_chunks:
                print(f"📤 Telegram: отправка продолжения текста chunks={len(remainder_chunks)}")
                for chunk in remainder_chunks:
                    msg_resp = tg_post(
                        "sendMessage",
                        data={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
                        timeout=(15, 35),
                        retries=2,
                    )
                    if msg_resp.status_code != 200:
                        print(f" Telegram continuation failed: {msg_resp.status_code} - {msg_resp.text[:200]}")
                        return {"ok": False, "error": f"Continuation message failed: {msg_resp.text}"}

            return response.json()
        elif text:
            payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
            print("📤 Telegram: отправка text message...")
            response = tg_post("sendMessage", data=payload, timeout=(15, 35), retries=2)
            print(f" Telegram response: {response.status_code} - {response.text[:200]}")
            return response.json() if response.status_code == 200 else {"ok": False, "error": response.text}
        else:
            return {"ok": False, "error": "Нет контента"}
    except requests.Timeout:
        print("⏱️ Telegram timeout")
        return {"ok": False, "error": "Telegram timeout"}
    except requests.RequestException as e:
        print(f"🌐 Telegram request error: {e}")
        return {"ok": False, "error": f"Telegram request error: {e}"}
    except Exception as e:
        print(f"🔥 Ошибка в send_to_telegram: {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}

# ============= ОТПРАВКА В MAX (С ПОДДЕРЖКОЙ ФАЙЛОВ) =============
def send_to_max(chat_id, text, files_data=None):
    print(f"📱 send_to_max: chat_id={chat_id}, files={len(files_data) if files_data else 0}")
    if not MAX_BOT_TOKEN:
        print("❌ MAX_BOT_TOKEN не задан")
        return {"ok": False, "error": "MAX_BOT_TOKEN not configured", "skipped": True}

    token_preview = MAX_BOT_TOKEN[:5] + "..." if len(MAX_BOT_TOKEN) > 5 else MAX_BOT_TOKEN
    print(f"🔑 Токен MAX (первые 5 символов): {token_preview}")

    message_attachments = []

    if files_data:
        for filename, content, mime_type in files_data:
            if 'image' in mime_type:
                file_type = 'image'
            elif 'video' in mime_type:
                file_type = 'video'
            else:
                print(f" ⚠️ Файл {filename} пропущен (неподдерживаемый тип {mime_type})")
                continue

            try:
                upload_req = requests.post(
                    "https://platform-api.max.ru/uploads",
                    params={'type': file_type},
                    headers={'Authorization': MAX_BOT_TOKEN},
                    timeout=30
                )
                if upload_req.status_code != 200:
                    print(f"   ❌ Не удалось получить URL: {upload_req.status_code} - {upload_req.text[:100]}")
                    continue
                upload_data = upload_req.json()
                if 'url' not in upload_data:
                    print(f"   ❌ Ответ /uploads не содержит url: {upload_data}")
                    continue
                upload_url = upload_data['url']
                print(f"   ✅ URL получен: {upload_url[:80]}...")

                files = {'data': (filename, content, mime_type)}
                headers_upload = {'Authorization': MAX_BOT_TOKEN}
                upload_file_resp = requests.post(
                    upload_url,
                    files=files,
                    headers=headers_upload,
                    timeout=60
                )
                if upload_file_resp.status_code != 200:
                    print(f"   ❌ Ошибка загрузки: {upload_file_resp.status_code} - {upload_file_resp.text[:200]}")
                    continue

                upload_result = upload_file_resp.json()
                print(f"   ✅ Ответ загрузки: {upload_result}")
                photos = upload_result.get('photos')
                if not photos:
                    print(f"   ❌ В ответе загрузки нет поля 'photos'")
                    continue
                first_photo_key = next(iter(photos))
                token_info = photos[first_photo_key]
                file_token = token_info.get('token')
                if not file_token:
                    print(f"   ❌ В ответе загрузки нет token в photos")
                    continue

                print(f"   ✅ Файл загружен, token={file_token[:10]}...")
                time.sleep(1.0)

                message_attachments.append({
                    'type': file_type,
                    'payload': {
                        'token': file_token,
                        'name': filename
                    }
                })
                print(f"   ✅ Вложение добавлено для {filename}")

            except Exception as e:
                print(f"🔥 Ошибка при обработке {filename}: {e}")
                import traceback
                traceback.print_exc()

    message_body = {}
    if text:
        message_body['text'] = text
        message_body['format'] = 'html'
    if message_attachments:
        message_body['attachments'] = message_attachments

    if not message_body:
        return {"ok": False, "error": "Нет контента для отправки", "skipped": True}

    try:
        print(f"   → Отправляем сообщение в MAX (текст={bool(text)}, вложений={len(message_attachments)})")
        send_msg_resp = requests.post(
            f"https://platform-api.max.ru/messages?chat_id={chat_id}",
            headers={'Authorization': MAX_BOT_TOKEN, 'Content-Type': 'application/json'},
            json=message_body,
            timeout=(8, 30)
        )
        if send_msg_resp.status_code == 200:
            print("   ✅ Сообщение в MAX отправлено")
            return {"ok": True, "result": send_msg_resp.json()}
        else:
            print(f"   ❌ Ошибка отправки сообщения: {send_msg_resp.status_code} - {send_msg_resp.text[:200]}")
            return {"ok": False, "error": send_msg_resp.text}
    except requests.Timeout:
        print("⏱️ MAX timeout")
        return {"ok": False, "error": "MAX timeout"}
    except requests.RequestException as e:
        print(f"🌐 MAX request error: {e}")
        return {"ok": False, "error": f"MAX request error: {e}"}
    except Exception as e:
        print(f"🔥 Ошибка при отправке сообщения: {e}")
        return {"ok": False, "error": str(e)}

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

            files_data = []
            for f in uploaded_files:
                content = f.read()
                files_data.append((f.filename, content, f.mimetype))
                app.logger.info(
                    "POST /post: file loaded name=%s size=%s mime=%s",
                    f.filename,
                    len(content),
                    f.mimetype,
                )

            if not telegram_chat_id:
                app.logger.warning("POST /post: missing telegram chat_id")
                if wants_json:
                    return jsonify({"error": "Не указан ID канала Telegram", "ok": False}), 400
                flash("Не указан ID канала Telegram", "danger")
                return _form_redirect_with_flash()

            final_text = build_post_text_payload(request.form, role)
            app.logger.info("POST /post: final_text_len=%s", len(final_text))

            payload = {
                "telegram_chat_id": telegram_chat_id,
                "max_chat_id": max_chat_id,
                "text": final_text,
                "files_data": files_data,
            }
            job_id = create_job(payload, {"username": current_username, "role": role})

            def _publish():
                tg_result = send_to_telegram(payload["telegram_chat_id"], payload["text"], payload["files_data"])
                max_result = {"ok": False, "skipped": True}
                if payload["max_chat_id"] and MAX_BOT_TOKEN:
                    max_result = send_to_max(payload["max_chat_id"], payload["text"], payload["files_data"])
                all_ok = (tg_result.get("ok", False) or tg_result.get("skipped", False)) and (
                    max_result.get("ok", False) or max_result.get("skipped", False)
                )
                return {"ok": all_ok, "telegram": tg_result, "max": max_result}

            run_job_async(job_id, _publish)

            if wants_json:
                return jsonify({"ok": True, "queued": True, "job_id": job_id}), 202

            flash(f"Публикация поставлена в очередь. ID задачи: {job_id[:8]}", "info")
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
        current_username, role = _resolve_user()
        if not current_username:
            return jsonify({"ok": False, "error": "Требуется авторизация"}), 401
        text = build_post_text_payload(request.get_json() or {}, role)
        return jsonify({"ok": True, "preview_text": text, "length": len(text)}), 200

    @app.route("/api/jobs/<job_id>", methods=["GET"])
    @csrf.exempt
    def get_job_status(job_id):
        job = get_job(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Job not found"}), 404
        return jsonify({"ok": True, "job": job}), 200

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception("Unhandled server error: %s", error)
        return jsonify({"ok": False, "error": "Внутренняя ошибка сервера"}), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
