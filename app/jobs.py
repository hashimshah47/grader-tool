"""Background jobs with a live event log the UI polls."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from typing import Callable


class Job:
    def __init__(self, kind: str) -> None:
        self.id = "job_" + uuid.uuid4().hex[:10]
        self.kind = kind
        self.status = "running"
        self.events: list[dict] = []
        self.result: dict | None = None
        self.error: str | None = None
        self.progress = {"done": 0, "total": 0}
        self.started = time.time()
        self._lock = threading.Lock()

    def log(self, message: str, level: str = "info", **data) -> None:
        with self._lock:
            self.events.append({"t": round(time.time() - self.started, 2), "level": level,
                                "message": message, **data})

    def set_progress(self, done: int, total: int) -> None:
        self.progress = {"done": done, "total": total}

    def to_dict(self, since: int = 0) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status,
                "events": self.events[since:], "event_count": len(self.events),
                "result": self.result, "error": self.error, "progress": self.progress,
                "elapsed": round(time.time() - self.started, 1)}


_jobs: dict[str, Job] = {}


def start(kind: str, fn: Callable[[Job], dict]) -> Job:
    job = Job(kind)
    _jobs[job.id] = job

    def run() -> None:
        try:
            job.result = fn(job)
            job.status = "done"
        except Exception as e:  # noqa: BLE001
            job.error = f"{type(e).__name__}: {e}"
            job.log(job.error, "error", detail=traceback.format_exc()[-2000:])
            job.status = "error"

    threading.Thread(target=run, daemon=True).start()
    # keep memory bounded
    if len(_jobs) > 200:
        for jid in sorted(_jobs, key=lambda j: _jobs[j].started)[:50]:
            if _jobs[jid].status != "running":
                _jobs.pop(jid, None)
    return job


def get(jid: str) -> Job:
    return _jobs[jid]
