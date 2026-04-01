"""
Отправка сообщений в MAX (platform-api.max.ru): загрузка файлов и отправка.
Ограничение API: не более 3 вложений на сообщение — остальные уходят отдельными сообщениями.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("app")

MAX_UPLOADS_URL = "https://platform-api.max.ru/uploads"
MAX_MESSAGES_URL = "https://platform-api.max.ru/messages"

# Документация MAX: в одном сообщении ограниченное число вложений (на практике — 3 фото).
MAX_ATTACHMENTS_PER_MESSAGE = 3


def _extract_token_from_upload_body(upload_result: Any, file_type: str) -> Optional[str]:
    """Достаёт token из ответа после заливки файла (разные схемы для image / video)."""
    if not isinstance(upload_result, dict):
        return None
    top = upload_result.get("token")
    if isinstance(top, str) and top:
        return top
    for key in ("photos", "videos", "files", "attachments", "images"):
        block = upload_result.get(key)
        if isinstance(block, dict):
            for v in block.values():
                if isinstance(v, dict):
                    t = v.get("token")
                    if isinstance(t, str) and t:
                        return t
                elif isinstance(v, str) and v:
                    return v
        elif isinstance(block, list) and block:
            first = block[0]
            if isinstance(first, dict) and first.get("token"):
                return first["token"]
    logger.warning("MAX upload: could not parse token from response keys=%s", list(upload_result.keys()))
    return None


def _max_upload_one(
    session: requests.Session,
    auth_token: str,
    filename: str,
    content: bytes,
    mime_type: str,
    file_type: str,
) -> Optional[Dict[str, Any]]:
    """Получить URL, залить файл, вернуть вложение для messages API."""
    try:
        upload_req = session.post(
            MAX_UPLOADS_URL,
            params={"type": file_type},
            headers={"Authorization": auth_token},
            timeout=(10, 45),
        )
        if upload_req.status_code != 200:
            logger.warning("MAX /uploads failed: %s %s", upload_req.status_code, upload_req.text[:200])
            return None
        upload_data = upload_req.json()
        if "url" not in upload_data:
            logger.warning("MAX /uploads missing url: %s", upload_data)
            return None
        upload_url = upload_data["url"]

        files = {"data": (filename, content, mime_type)}
        upload_file_resp = session.post(
            upload_url,
            files=files,
            headers={"Authorization": auth_token},
            timeout=(30, 120),
        )
        if upload_file_resp.status_code != 200:
            logger.warning(
                "MAX file upload failed: %s %s", upload_file_resp.status_code, upload_file_resp.text[:300]
            )
            return None

        try:
            upload_result = upload_file_resp.json()
        except json.JSONDecodeError:
            logger.warning("MAX upload response not JSON: %s", upload_file_resp.text[:200])
            return None

        token = _extract_token_from_upload_body(upload_result, file_type)
        if not token:
            logger.warning("MAX upload: no token in body: %s", str(upload_result)[:500])
            return None

        return {
            "type": file_type,
            "payload": {"token": token, "name": filename},
        }
    except requests.RequestException as e:
        logger.warning("MAX upload request error: %s", e)
        return None


def _max_send_message(
    session: requests.Session,
    auth_token: str,
    chat_id: str,
    message_body: Dict[str, Any],
    max_retries: int = 6,
) -> Tuple[bool, Any]:
    """Отправка с повтором при attachment.not.ready (видео обрабатывается на стороне MAX)."""
    url = f"{MAX_MESSAGES_URL}?chat_id={chat_id}"
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = session.post(
                url,
                headers={"Authorization": auth_token, "Content-Type": "application/json"},
                json=message_body,
                timeout=(10, 60),
            )
            if resp.status_code == 200:
                return True, resp.json()
            text = (resp.text or "")[:500]
            last_err = text
            if resp.status_code >= 400 and ("not.ready" in text.lower() or "not_ready" in text.lower()):
                delay = min(2.0, 0.4 * (2**attempt))
                logger.info("MAX message: attachment not ready, retry in %ss", delay)
                time.sleep(delay)
                continue
            return False, text
        except requests.Timeout:
            last_err = "timeout"
            time.sleep(0.5 * (attempt + 1))
    return False, last_err or "MAX send failed"


def send_to_max(chat_id: str, text: Optional[str], files_data: Optional[List[Tuple[str, bytes, str]]], auth_token: str):
    """
    files_data: список (filename, bytes, mime) после prepare_files_for_publish.
    """
    logger.info("send_to_max: chat_id=%s files=%s", chat_id, len(files_data) if files_data else 0)
    if not auth_token:
        return {"ok": False, "error": "MAX_BOT_TOKEN not configured", "skipped": True}

    session = requests.Session()
    message_attachments: List[Dict[str, Any]] = []

    if files_data:
        for filename, content, mime_type in files_data:
            mt = (mime_type or "").lower()
            if "image" in mt or mt in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                file_type = "image"
            elif "video" in mt or mt.startswith("video/"):
                file_type = "video"
            else:
                logger.warning("MAX: skip unsupported mime %s for %s", mime_type, filename)
                continue

            att = _max_upload_one(session, auth_token, filename or "file", content, mime_type, file_type)
            if att:
                message_attachments.append(att)

    if not text and not message_attachments:
        return {"ok": False, "error": "Нет контента для отправки", "skipped": True}

    # Разбиваем на сообщения по MAX_ATTACHMENTS_PER_MESSAGE вложений
    chunks: List[List[Dict[str, Any]]] = []
    if message_attachments:
        step = MAX_ATTACHMENTS_PER_MESSAGE
        for i in range(0, len(message_attachments), step):
            chunks.append(message_attachments[i : i + step])
    else:
        chunks = [[]]

    results = []
    for idx, batch in enumerate(chunks):
        message_body: Dict[str, Any] = {}
        if text and idx == 0:
            message_body["text"] = text
            message_body["format"] = "html"
        if batch:
            message_body["attachments"] = batch
        if not message_body:
            continue
        ok, data = _max_send_message(session, auth_token, chat_id, message_body)
        results.append({"ok": ok, "result": data})
        if not ok:
            return {"ok": False, "error": data, "partial": results}

    return {"ok": True, "result": results[-1]["result"] if results else {}, "batches": len(chunks)}
