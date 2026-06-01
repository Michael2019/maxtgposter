"""
Публикация в Telegram: фото альбомами, видео по одному (API нестабилен при смешанных media group).
"""
from __future__ import annotations

import json
import logging
import os
import time
from html import escape
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from services.media_files import sniff_telegram_media_kind

logger = logging.getLogger("app")

TELEGRAM_API_BASE_URL = os.environ.get("TELEGRAM_API_BASE_URL", "https://api.telegram.org")
TELEGRAM_PROXY_URL = os.environ.get("TELEGRAM_PROXY_URL")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TELEGRAM_API_URL = f"{TELEGRAM_API_BASE_URL}/bot{BOT_TOKEN}" if BOT_TOKEN else ""

FileTuple = Tuple[str, bytes, str]


def escape_telegram_html(text: str) -> str:
    return escape(text or "", quote=False)


def partition_media_files(files_data: List[FileTuple]) -> Tuple[List[FileTuple], List[FileTuple], List[FileTuple]]:
    photos: List[FileTuple] = []
    videos: List[FileTuple] = []
    other: List[FileTuple] = []
    for item in files_data:
        filename, content, mime = item
        if not content:
            logger.warning("Telegram: skip empty file %s", filename)
            continue
        kind = sniff_telegram_media_kind(filename, mime)
        if kind == "photo":
            photos.append(item)
        elif kind == "video":
            videos.append(item)
        else:
            other.append(item)
    return photos, videos, other


def _rewind_multipart_files(files) -> None:
    if not files:
        return

    def rewind_obj(fobj):
        if fobj is not None and hasattr(fobj, "seek"):
            try:
                fobj.seek(0)
            except (OSError, ValueError):
                pass

    if isinstance(files, dict):
        for val in files.values():
            if isinstance(val, (list, tuple)) and len(val) >= 2:
                rewind_obj(val[1])
    elif isinstance(files, (list, tuple)):
        for item in files:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            inner = item[1]
            if isinstance(inner, (list, tuple)) and len(inner) >= 2:
                rewind_obj(inner[1])


def _parse_telegram_response(response: requests.Response) -> Dict[str, Any]:
    if response.status_code != 200:
        return {"ok": False, "error": response.text}
    try:
        data = response.json()
    except ValueError:
        return {"ok": False, "error": response.text}
    if not data.get("ok"):
        return {"ok": False, "error": data.get("description") or response.text}
    return data


def send_to_telegram(chat_id: str, text: Optional[str], files_data: Optional[List[FileTuple]]) -> Dict[str, Any]:
    if not BOT_TOKEN or not TELEGRAM_API_URL:
        return {"ok": False, "error": "BOT_TOKEN not configured"}

    files_data = files_data or []
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
                    _rewind_multipart_files(files)
                    time.sleep(1.2 * attempt)
            except requests.RequestException as e:
                last_error = e
                logger.warning("Telegram request exception endpoint=%s attempt=%s error=%s", endpoint, attempt, e)
                if attempt < retries:
                    _rewind_multipart_files(files)
                    time.sleep(1.2 * attempt)
        if isinstance(last_error, requests.Timeout):
            raise requests.Timeout()
        raise requests.RequestException(last_error or "Unknown Telegram request error")

    def send_remainder_chunks(chunks: List[str]) -> Optional[Dict[str, Any]]:
        for chunk in chunks:
            msg_resp = tg_post(
                "sendMessage",
                data={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
                timeout=(15, 35),
                retries=2,
            )
            parsed = _parse_telegram_response(msg_resp)
            if not parsed.get("ok"):
                return parsed
        return None

    try:
        safe_text = escape_telegram_html(text or "")
        logger.info("send_to_telegram: chat_id=%s files=%s", chat_id, len(files_data))

        if not files_data:
            if not safe_text:
                return {"ok": False, "error": "Нет контента"}
            payload = {"chat_id": chat_id, "text": safe_text, "parse_mode": "HTML"}
            response = tg_post("sendMessage", data=payload, timeout=(15, 35), retries=2)
            return _parse_telegram_response(response)

        caption_limit = 1024
        caption_text = safe_text[:caption_limit] if safe_text else ""
        remainder_text = safe_text[caption_limit:] if len(safe_text) > caption_limit else ""
        remainder_chunks = _split_text_chunks(remainder_text, 4096)

        photos, videos, other = partition_media_files(files_data)

        # Один нераспознанный файл — как документ
        if not photos and not videos and len(other) == 1:
            filename, content, mime_type = other[0]
            payload_doc = {"chat_id": chat_id, "caption": caption_text, "parse_mode": "HTML"}
            files_doc = {
                "document": (filename or "file.bin", BytesIO(content), mime_type or "application/octet-stream"),
            }
            response = tg_post("sendDocument", data=payload_doc, files=files_doc, timeout=(15, 120), retries=2)
            parsed = _parse_telegram_response(response)
            if not parsed.get("ok"):
                return parsed
            err = send_remainder_chunks(remainder_chunks)
            return err if err else parsed

        if not photos and not videos:
            return {"ok": False, "error": "Нет поддерживаемых файлов (фото/видео)"}

        caption_used = False
        last_ok: Dict[str, Any] = {"ok": True}

        def next_caption() -> str:
            nonlocal caption_used
            if caption_used or not caption_text:
                return ""
            caption_used = True
            return caption_text

        # Фото — только альбомы из фото (до 10)
        for offset in range(0, len(photos), 10):
            batch = photos[offset : offset + 10]
            cap = next_caption()
            parsed = _send_photo_batch(tg_post, chat_id, batch, cap)
            if not parsed.get("ok"):
                return parsed
            last_ok = parsed

        # Видео — по одному (смешанный media group с фото часто падает)
        for video_item in videos:
            cap = next_caption()
            parsed = _send_single_video(tg_post, chat_id, video_item, cap)
            if not parsed.get("ok"):
                return parsed
            last_ok = parsed

        if other:
            logger.warning("Telegram: %s unsupported file(s) skipped", len(other))

        err = send_remainder_chunks(remainder_chunks)
        if err:
            return err
        return last_ok

    except requests.Timeout:
        logger.warning("Telegram timeout")
        return {"ok": False, "error": "Telegram timeout"}
    except requests.RequestException as e:
        logger.warning("Telegram request error: %s", e)
        return {"ok": False, "error": f"Telegram request error: {e}"}
    except Exception as e:
        logger.exception("send_to_telegram failed: %s", e)
        return {"ok": False, "error": str(e)}


def _split_text_chunks(text: str, chunk_size: int) -> List[str]:
    text = text or ""
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _send_single_video(
    tg_post: Callable,
    chat_id: str,
    video_item: FileTuple,
    caption: str,
) -> Dict[str, Any]:
    filename, content, mime = video_item
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "supports_streaming": "true",
    }
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "HTML"
    files_for_tg = {"video": (filename, BytesIO(content), mime or "video/mp4")}
    logger.info("Telegram: sendVideo %s (%s bytes)", filename, len(content))
    response = tg_post("sendVideo", data=payload, files=files_for_tg, timeout=(30, 300), retries=2)
    return _parse_telegram_response(response)


def _send_photo_batch(
    tg_post: Callable,
    chat_id: str,
    batch: List[FileTuple],
    caption: str,
) -> Dict[str, Any]:
    if len(batch) == 1:
        filename, content, mime = batch[0]
        payload: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            payload["caption"] = caption
            payload["parse_mode"] = "HTML"
        files_for_tg = {"photo": (filename, BytesIO(content), mime or "image/jpeg")}
        logger.info("Telegram: sendPhoto %s", filename)
        response = tg_post("sendPhoto", data=payload, files=files_for_tg, timeout=(30, 120), retries=2)
        return _parse_telegram_response(response)

    media = []
    attachments: Dict[str, Tuple[str, BytesIO, str]] = {}
    for media_idx, (filename, content, mime) in enumerate(batch):
        attach_name = f"file{media_idx}"
        media_item: Dict[str, Any] = {"type": "photo", "media": f"attach://{attach_name}"}
        if media_idx == 0 and caption:
            media_item["caption"] = caption
            media_item["parse_mode"] = "HTML"
        media.append(media_item)
        attachments[attach_name] = (filename, BytesIO(content), mime or "image/jpeg")

    payload = {"chat_id": chat_id, "media": json.dumps(media)}
    files_for_tg = [(name, (fname, stream, mt)) for name, (fname, stream, mt) in attachments.items()]
    logger.info("Telegram: sendMediaGroup photos=%s", len(batch))
    response = tg_post("sendMediaGroup", data=payload, files=files_for_tg, timeout=(45, 180), retries=2)
    return _parse_telegram_response(response)
