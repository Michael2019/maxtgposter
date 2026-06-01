"""
Очередь публикаций и история отправок.

История хранится в JSON-файле (с блокировкой) и дублируется в Google Sheets,
чтобы на Render (несколько воркеров / перезапуски) список в админке не «прыгал».
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("app")

_executor = ThreadPoolExecutor(max_workers=4)
_lock = threading.RLock()
_jobs: Dict[str, dict] = {}

HISTORY_MAX_LEN = int(os.environ.get("PUBLISH_HISTORY_MAX", "500"))
_history_file = Path(os.environ.get("PUBLISH_HISTORY_FILE", "data/publish_history.json"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_summary(result: Any) -> dict:
    if isinstance(result, dict) and set(result.keys()) <= {"error"}:
        return {"error": str(result.get("error") or "")[:500]}
    if not isinstance(result, dict):
        return {"note": str(result)[:500]}
    out: Dict[str, Any] = {}
    if "ok" in result:
        out["ok"] = result.get("ok")
    tg = result.get("telegram")
    if isinstance(tg, dict):
        out["telegram_ok"] = tg.get("ok")
        if not tg.get("ok"):
            out["telegram_error"] = str(tg.get("error") or tg.get("description") or "")[:400]
    mx = result.get("max")
    if isinstance(mx, dict):
        if mx.get("skipped"):
            out["max_ok"] = "skipped"
        else:
            out["max_ok"] = mx.get("ok")
            if not mx.get("ok"):
                out["max_error"] = str(mx.get("error") or "")[:400]
    if not out and result.get("error"):
        out["error"] = str(result.get("error"))[:500]
    return out


def _normalize_history_entry(entry: dict) -> dict:
    user = entry.get("user") or {}
    username = user.get("username") if isinstance(user, dict) else str(user or "")
    summary = entry.get("summary")
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except (json.JSONDecodeError, TypeError):
            summary = {"note": summary[:500]}
    return {
        "id": str(entry.get("id") or ""),
        "created_at": str(entry.get("created_at") or ""),
        "finished_at": str(entry.get("finished_at") or ""),
        "status": str(entry.get("status") or ""),
        "user": {"username": str(username or "").strip()},
        "channel": str(entry.get("channel") or "").strip(),
        "summary": _compact_summary(summary),
    }


def _file_lock(handle) -> None:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except (ImportError, AttributeError, OSError):
        pass


def _file_unlock(handle) -> None:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (ImportError, AttributeError, OSError):
        pass


def _read_history_file() -> List[dict]:
    _history_file.parent.mkdir(parents=True, exist_ok=True)
    if not _history_file.exists():
        return []
    try:
        with open(_history_file, "r", encoding="utf-8") as handle:
            _file_lock(handle)
            try:
                raw = handle.read().strip()
                if not raw:
                    return []
                data = json.loads(raw)
                if not isinstance(data, list):
                    return []
                out = []
                for x in data:
                    if not isinstance(x, dict):
                        continue
                    try:
                        out.append(_normalize_history_entry(x))
                    except Exception as exc:
                        logger.warning("publish history: skip bad row: %s", exc)
                return out
            finally:
                _file_unlock(handle)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning("publish history: read file failed: %s", exc)
        return []


def _write_history_file(items: List[dict]) -> None:
    _history_file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(items[:HISTORY_MAX_LEN], ensure_ascii=False)
    tmp_path = _history_file.with_suffix(_history_file.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            _file_lock(handle)
            try:
                handle.write(payload)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            finally:
                _file_unlock(handle)
        tmp_path.replace(_history_file)
    except OSError as exc:
        logger.exception("publish history: write file failed: %s", exc)


def _read_history_sheets() -> List[dict]:
    try:
        from flask import has_app_context

        if not has_app_context():
            return []
        from services.sheets import sheets_service

        return sheets_service.get_publish_history(HISTORY_MAX_LEN)
    except Exception as exc:
        logger.warning("publish history: read sheets failed: %s", exc)
        return []


def _append_history_sheets(entry: dict) -> None:
    try:
        from flask import has_app_context

        if not has_app_context():
            return
        from services.sheets import sheets_service

        sheets_service.append_publish_history(entry)
    except Exception as exc:
        logger.warning("publish history: append sheets failed: %s", exc)


def _merge_history(*sources: List[dict]) -> List[dict]:
    by_id: Dict[str, dict] = {}
    for items in sources:
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            existing = by_id.get(item_id)
            if not existing:
                by_id[item_id] = item
                continue
            # Оставляем запись с более поздним finished_at
            ex_fin = existing.get("finished_at") or ""
            new_fin = item.get("finished_at") or ""
            if new_fin >= ex_fin:
                by_id[item_id] = item

    merged = list(by_id.values())
    merged.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return merged


def list_history(limit: int = 100, *, use_sheets: bool = True) -> List[dict]:
    try:
        with _lock:
            file_items = _read_history_file()
        sheet_items = _read_history_sheets() if use_sheets else []
        merged = _merge_history(file_items, sheet_items)
        return merged[:limit]
    except Exception as exc:
        logger.exception("list_history failed: %s", exc)
        return []


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def list_history_between(start_dt=None, end_dt=None, limit: int = 500, *, use_sheets: bool = True) -> List[dict]:
    items = list_history(limit=limit, use_sheets=use_sheets)
    if not start_dt and not end_dt:
        return items
    filtered = []
    for item in items:
        # Фильтр по дате завершения — ближе к факту публикации
        point = _parse_iso_datetime(item.get("finished_at")) or _parse_iso_datetime(item.get("created_at"))
        if not point:
            continue
        if start_dt and point < start_dt:
            continue
        if end_dt and point > end_dt:
            continue
        filtered.append(item)
    return filtered


def _append_history(entry: dict) -> None:
    normalized = _normalize_history_entry(entry)
    entry_id = normalized.get("id")
    if not entry_id:
        return

    with _lock:
        items = _read_history_file()
        items = [x for x in items if x.get("id") != entry_id]
        items.insert(0, normalized)
        _write_history_file(items)

    _append_history_sheets(normalized)


def create_job(payload, user):
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "status": "queued",
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "user": user,
        "payload": payload,
        "result": None,
        "error": None,
    }
    with _lock:
        _jobs[job_id] = job
    return job_id


def update_job(job_id, **fields):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def get_job(job_id):
    with _lock:
        return dict(_jobs[job_id]) if job_id in _jobs else None


def run_job_async(job_id, fn):
    app = None
    try:
        from flask import current_app

        app = current_app._get_current_object()
    except RuntimeError:
        pass

    def _runner():
        ctx = app.app_context() if app else None
        try:
            if ctx:
                ctx.push()
            update_job(job_id, status="running", started_at=_now_iso())
            try:
                result = fn()
                finished_at = _now_iso()
                status = "done"
                if isinstance(result, dict) and result.get("ok") is False:
                    status = "failed"
                    update_job(
                        job_id,
                        status=status,
                        finished_at=finished_at,
                        result=result,
                        error=str(result.get("error") or "publish failed"),
                    )
                else:
                    update_job(job_id, status=status, finished_at=finished_at, result=result)
                with _lock:
                    created_at = _jobs.get(job_id, {}).get("created_at")
                    user = _jobs.get(job_id, {}).get("user")
                    payload = _jobs.get(job_id, {}).get("payload") or {}
                _append_history(
                    {
                        "id": job_id,
                        "created_at": created_at,
                        "finished_at": finished_at,
                        "status": status,
                        "user": user,
                        "channel": payload.get("channel", ""),
                        "summary": result,
                    }
                )
            except Exception as exc:
                finished_at = _now_iso()
                update_job(job_id, status="failed", finished_at=finished_at, error=str(exc))
                with _lock:
                    created_at = _jobs.get(job_id, {}).get("created_at")
                    user = _jobs.get(job_id, {}).get("user")
                    payload = _jobs.get(job_id, {}).get("payload") or {}
                _append_history(
                    {
                        "id": job_id,
                        "created_at": created_at,
                        "finished_at": finished_at,
                        "status": "failed",
                        "user": user,
                        "channel": payload.get("channel", ""),
                        "summary": {"error": str(exc)},
                    }
                )
        finally:
            if ctx:
                ctx.pop()

    _executor.submit(_runner)
