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

from services.media_files import sniff_telegram_media_kind

logger = logging.getLogger("app")

MAX_UPLOADS_URL = "https://platform-api.max.ru/uploads"
MAX_MESSAGES_URL = "https://platform-api.max.ru/messages"

# Документация MAX: в одном сообщении ограниченное число вложений (на практике — 3 фото).
MAX_ATTACHMENTS_PER_MESSAGE = 3


def _extract_token_from_upload_body(upload_result: Any, file_type: str) -> Optional[str]:
    """Достаёт token из ответа после заливки (image/file) или из retval/вложенных структур (video)."""
    if upload_result is None:
        return None
    if isinstance(upload_result, str) and upload_result.strip():
        return upload_result.strip()
    if not isinstance(upload_result, dict):
        return None
    top = upload_result.get("token")
    if isinstance(top, str) and top:
        return top
    # MAX для видео/аудио иногда возвращает retval (строка или объект)
    rv = upload_result.get("retval")
    if isinstance(rv, str) and rv.strip():
        return rv.strip()
    if isinstance(rv, dict):
        t = rv.get("token")
        if isinstance(t, str) and t:
            return t
    for key in ("photos", "videos", "files", "attachments", "images", "video"):
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
        # Для video/audio в ответе POST /uploads иногда сразу есть token (документация dev.max.ru)
        token_from_slot = upload_data.get("token")
        if isinstance(token_from_slot, str) and token_from_slot:
            logger.info("MAX /uploads returned token in first response (type=%s)", file_type)

        files = {"data": (filename, content, mime_type)}
        upload_file_resp = session.post(
            upload_url,
            files=files,
            headers={"Authorization": auth_token},
            timeout=(30, 300),
        )
        if upload_file_resp.status_code != 200:
            logger.warning(
                "MAX file upload failed: %s %s", upload_file_resp.status_code, upload_file_resp.text[:300]
            )
            return None

        upload_result: Any = None
        if upload_file_resp.text and upload_file_resp.text.strip():
            try:
                upload_result = upload_file_resp.json()
            except json.JSONDecodeError:
                logger.warning("MAX upload response not JSON: %s", upload_file_resp.text[:200])
                upload_result = None

        token = _extract_token_from_upload_body(upload_result, file_type) if upload_result else None
        if not token and isinstance(token_from_slot, str) and token_from_slot:
            token = token_from_slot
            logger.info("MAX: using token from POST /uploads (after CDN upload ok)")
        if not token:
            logger.warning(
                "MAX upload: no token (after CDN). first=%s second=%s",
                str(upload_data)[:400],
                str(upload_result)[:400] if upload_result is not None else "null",
            )
            return None

        # Видео в API MAX: в примере только token в payload; лишнее поле name может мешать
        if file_type == "video":
            payload: Dict[str, Any] = {"token": token}
        else:
            payload = {"token": token, "name": filename or "file"}

        return {"type": file_type, "payload": payload}
    except requests.RequestException as e:
        logger.warning("MAX upload request error: %s", e)
        return None


def _max_send_message(
    session: requests.Session,
    auth_token: str,
    chat_id: str,
    message_body: Dict[str, Any],
    max_retries: int = 12,
) -> Tuple[bool, Any]:
    """Отправка с повтором при attachment.not.ready (видео обрабатывается на стороне MAX)."""
    url = f"{MAX_MESSAGES_URL}?chat_id={chat_id}"
    last_err = None
    has_video = any(
        (a.get("type") == "video") for a in (message_body.get("attachments") or []) if isinstance(a, dict)
    )
    for attempt in range(max_retries):
        try:
            resp = session.post(
                url,
                headers={"Authorization": auth_token, "Content-Type": "application/json"},
                json=message_body,
                timeout=(15, 120 if has_video else 60),
            )
            if resp.status_code == 200:
                return True, resp.json()
            text = (resp.text or "")[:800]
            last_err = text
            retry_later = False
            if resp.status_code >= 400:
                low = text.lower()
                if "not.ready" in low or "not_ready" in low or "not.processed" in low:
                    retry_later = True
                else:
                    try:
                        err_j = resp.json()
                        code = str(err_j.get("code", "") or "")
                        msg = str(err_j.get("message", "") or "")
                        if "not.ready" in code.lower() or "not.processed" in msg.lower():
                            retry_later = True
                    except (json.JSONDecodeError, ValueError):
                        pass
            if retry_later:
                delay = min(8.0, 0.6 * (1.6**attempt))
                logger.info("MAX message: attachment not ready, retry in %.1fs (attempt %s)", delay, attempt + 1)
                time.sleep(delay)
                continue
            return False, text
        except requests.Timeout:
            last_err = "timeout"
            time.sleep(min(5.0, 0.8 * (attempt + 1)))
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
            if not content:
                logger.warning("MAX: skip empty file %s", filename)
                continue
            kind = sniff_telegram_media_kind(filename or "", mime_type or "")
            if kind == "photo":
                file_type = "image"
            elif kind == "video":
                file_type = "video"
            else:
                mt = (mime_type or "").lower()
                if "image" in mt:
                    file_type = "image"
                elif "video" in mt or mt.startswith("video/"):
                    file_type = "video"
                else:
                    logger.warning("MAX: skip unsupported file %s (mime=%s)", filename, mime_type)
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
