from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import uuid


_executor = ThreadPoolExecutor(max_workers=4)
_lock = threading.Lock()
_jobs = {}
_history = deque(maxlen=500)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


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


def _append_history(entry):
    with _lock:
        _history.appendleft(entry)


def run_job_async(job_id, fn):
    def _runner():
        update_job(job_id, status="running", started_at=_now_iso())
        try:
            result = fn()
            update_job(job_id, status="done", finished_at=_now_iso(), result=result)
            _append_history(
                {
                    "id": job_id,
                    "created_at": _jobs[job_id]["created_at"],
                    "finished_at": _now_iso(),
                    "status": "done",
                    "user": _jobs[job_id]["user"],
                    "summary": result,
                }
            )
        except Exception as exc:
            update_job(job_id, status="failed", finished_at=_now_iso(), error=str(exc))
            _append_history(
                {
                    "id": job_id,
                    "created_at": _jobs[job_id]["created_at"],
                    "finished_at": _now_iso(),
                    "status": "failed",
                    "user": _jobs[job_id]["user"],
                    "summary": {"error": str(exc)},
                }
            )

    _executor.submit(_runner)
