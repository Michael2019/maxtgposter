"""
Нормализация вложений перед публикацией: HEIC/HEIF → JPEG, уточнение MIME для видео,
опционально — перекодирование видео в H.264/AAC MP4 для стабильного воспроизведения в Telegram на iOS.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from typing import List, Optional, Tuple

logger = logging.getLogger("app")

TELEGRAM_MAX_BYTES = int(float(os.environ.get("TELEGRAM_MAX_UPLOAD_MB", "48")) * 1024 * 1024)

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
        if not content:
            logger.warning("Skip empty upload: %s", fn)
            continue
        if len(content) > TELEGRAM_MAX_BYTES:
            logger.warning("File too large for Telegram (%s bytes): %s", len(content), fn)
            continue
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


def _video_needs_transcode_for_telegram(filename: str, mime: str, path: str) -> bool:
    """Эвристика + ffprobe: что часто ломается в Telegram на iPhone."""
    lower = (filename or "").lower()
    m = (mime or "").lower()
    ext = os.path.splitext(lower)[1]

    if ext in (".webm", ".mkv", ".avi", ".3gp", ".mpeg", ".mpg"):
        return True
    if "webm" in m or m == "video/x-matroska":
        return True
    if ext == ".mov" or "quicktime" in m:
        return True

    ffprobe = shutil.which("ffprobe")
    if not ffprobe or ext != ".mp4":
        return False
    try:
        r = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=nw=1:nk=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if r.returncode != 0:
            return False
        codec = (r.stdout or "").strip().lower()
        if codec in ("hevc", "h265", "vp9", "av1", "mpeg2video"):
            return True
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return False


def _transcode_video_ffmpeg(filename: str, content: bytes) -> Optional[Tuple[str, bytes, str]]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.info("ffmpeg not found; skip video transcode for Telegram/iOS compatibility")
        return None

    in_suffix = os.path.splitext(filename or "")[1] or ".bin"
    out_path = None
    in_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=in_suffix, delete=False) as fin:
            fin.write(content)
            in_path = fin.name

        fd, out_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)

        def _run_ffmpeg(with_audio: bool) -> subprocess.CompletedProcess:
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                in_path,
                "-map",
                "0:v:0",
                "-c:v",
                "libx264",
                "-profile:v",
                "high",
                "-level",
                "4.1",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
            ]
            if with_audio:
                cmd.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "128k"])
            else:
                cmd.append("-an")
            cmd.append(out_path)
            return subprocess.run(cmd, capture_output=True, timeout=600)

        r = _run_ffmpeg(with_audio=True)
        if r.returncode != 0:
            err = (r.stderr or b"").decode("utf-8", errors="replace")[:800]
            if "does not contain" in err.lower() or "stream map" in err.lower():
                logger.info("ffmpeg: retry without audio for %s", filename)
                r = _run_ffmpeg(with_audio=False)
            if r.returncode != 0:
                logger.warning("ffmpeg transcode failed for %s: %s", filename, err)
                return None
        with open(out_path, "rb") as f:
            out_bytes = f.read()
        if not out_bytes:
            return None
        base = os.path.splitext(filename or "video")[0] or "video"
        return (f"{base}_h264.mp4", out_bytes, "video/mp4")
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg transcode timeout for %s", filename)
        return None
    except OSError as e:
        logger.warning("ffmpeg transcode OS error for %s: %s", filename, e)
        return None
    finally:
        for p in (in_path, out_path):
            if p and os.path.isfile(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


def ensure_telegram_friendly_videos(
    files_data: List[Tuple[str, bytes, str]],
) -> List[Tuple[str, bytes, str]]:
    """
    Для видео, которые часто плохо открываются в Telegram на iOS (WebM, MOV/HEVC, и т.д.),
    перекодируем в H.264 + AAC MP4 с faststart, если в PATH есть ffmpeg.
    Отключить: TELEGRAM_VIDEO_TRANSCODE=0
    """
    if os.environ.get("TELEGRAM_VIDEO_TRANSCODE", "1").strip().lower() in ("0", "false", "no"):
        return files_data

    if not shutil.which("ffmpeg"):
        return files_data

    out: List[Tuple[str, bytes, str]] = []
    for filename, content, mime in files_data:
        if sniff_telegram_media_kind(filename, mime) != "video":
            out.append((filename, content, mime))
            continue

        in_suffix = os.path.splitext(filename or "")[1] or ".mp4"
        probe_path = None
        needs = False
        try:
            with tempfile.NamedTemporaryFile(suffix=in_suffix, delete=False) as fin:
                fin.write(content)
                probe_path = fin.name
            needs = _video_needs_transcode_for_telegram(filename, mime, probe_path)
        except OSError:
            out.append((filename, content, mime))
            continue
        finally:
            if probe_path and os.path.isfile(probe_path):
                try:
                    os.unlink(probe_path)
                except OSError:
                    pass

        if not needs:
            out.append((filename, content, mime))
            continue

        converted = _transcode_video_ffmpeg(filename, content)
        if converted:
            logger.info("Video transcoded for Telegram: %s -> %s", filename, converted[0])
            out.append(converted)
        else:
            out.append((filename, content, mime))

    return out
