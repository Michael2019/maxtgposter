from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import uuid


_executor = ThreadPoolExecutor(max_workers=4)
_lock = threading.Lock()
_jobs = {}
_history = deque(maxlen=500)
_history_file = Path(os.environ.get("PUBLISH_HISTORY_FILE", "data/publish_history.json"))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _persist_history_to_disk():
    try:
        _history_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = _history_file.with_suffix(_history_file.suffix + ".tmp")
        tmp_file.write_text(json.dumps(list(_history), ensure_ascii=False), encoding="utf-8")
        tmp_file.replace(_history_file)
    except Exception:
        # История в памяти продолжит работать, даже если запись на диск недоступна.
        pass


def _load_history_from_disk():
    if not _history_file.exists():
        return
    try:
        raw = _history_file.read_text(encoding="utf-8").strip()
        if not raw:
            return
        data = json.loads(raw)
        if isinstance(data, list):
            _history.clear()
            for item in data[: _history.maxlen]:
                if isinstance(item, dict):
                    _history.append(item)
    except Exception:
        # Битый файл не должен ломать запуск приложения.
        return


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
        return dict(_jobs.get(job_id)) if job_id in _jobs else None


def list_history(limit=100):
    with _lock:
        data = list(_history)
    return data[:limit]


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def list_history_between(start_dt=None, end_dt=None, limit=500):
    items = list_history(limit=limit)
    if not start_dt and not end_dt:
        return items
    filtered = []
    for item in items:
        created = _parse_iso_datetime(item.get("created_at"))
        if not created:
            continue
        if start_dt and created < start_dt:
            continue
        if end_dt and created > end_dt:
            continue
        filtered.append(item)
    return filtered


def _append_history(entry):
    with _lock:
        _history.appendleft(entry)
        _persist_history_to_disk()


def run_job_async(job_id, fn):
    def _runner():
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

    _executor.submit(_runner)


_load_history_from_disk()
