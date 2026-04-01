"""
Нормализация вложений перед публикацией: HEIC/HEIF → JPEG, уточнение MIME для видео.
"""
from __future__ import annotations

import logging
import os
from io import BytesIO
from typing import List, Optional, Tuple

logger = logging.getLogger("app")

# Расширения, которые считаем видео, если браузер отдал неверный MIME
_VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".mpeg", ".mpg", ".3gp")
_IMAGE_EXT = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".heic",
    ".heif",
)


def sniff_telegram_media_kind(filename: str, mime: str) -> Optional[str]:
    """
    'photo' | 'video' | None
    None — тип не распознан (можно отправить как document отдельно).
    """
    name = (filename or "").lower()
    m = (mime or "").lower()
    if m.startswith("video/"):
        return "video"
    if any(name.endswith(ext) for ext in _VIDEO_EXT):
        return "video"
    if m.startswith("image/"):
        return "photo"
    if any(name.endswith(ext) for ext in _IMAGE_EXT):
        return "photo"
    return None


def _convert_heic_to_jpeg(filename: str, content: bytes) -> Optional[Tuple[str, bytes, str]]:
    try:
        from pillow_heif import register_heif_opener  # type: ignore

        register_heif_opener()
        from PIL import Image

        img = Image.open(BytesIO(content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="JPEG", quality=92, optimize=True)
        base = os.path.splitext(filename or "photo")[0] or "photo"
        return (f"{base}.jpg", out.getvalue(), "image/jpeg")
    except ImportError:
        logger.info("pillow-heif not installed; HEIC will be passed through if possible")
        return None
    except Exception as e:
        logger.warning("HEIC/HEIF conversion failed for %s: %s", filename, e)
        return None


def prepare_files_for_publish(
    files_data: List[Tuple[str, bytes, str]],
) -> List[Tuple[str, bytes, str]]:
    """
    Принимает список (filename, content, mimetype) из request.files.
    Возвращает нормализованный список для Telegram/MAX.
    """
    out: List[Tuple[str, bytes, str]] = []
    for filename, content, mime in files_data:
        fn = filename or "file"
        m = (mime or "application/octet-stream").lower()
        lower = fn.lower()

        if m in ("image/heic", "image/heif") or lower.endswith((".heic", ".heif")):
            converted = _convert_heic_to_jpeg(fn, content)
            if converted:
                out.append(converted)
                continue
            # без конвертации — пробуем как есть (часть окружений откроет через Pillow без heif)
            logger.info("Passing HEIC without conversion: %s", fn)

        # Уточняем MIME для видео по расширению
        if any(lower.endswith(ext) for ext in _VIDEO_EXT) and not m.startswith("video/"):
            if lower.endswith(".mov"):
                m = "video/quicktime"
            elif lower.endswith(".webm"):
                m = "video/webm"
            else:
                m = "video/mp4"

        out.append((fn, content, m))
    return out
