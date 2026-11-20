"""File-based persistence: projects (rubric + checker versions) and grading runs."""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import config

_lock = threading.RLock()
PROJECTS = config.DATA_DIR / "projects"
RUNS = config.DATA_DIR / "runs"
PROJECTS.mkdir(parents=True, exist_ok=True)
RUNS.mkdir(parents=True, exist_ok=True)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _safe(id_: str) -> str:
    if not id_.replace("_", "").isalnum():
        raise KeyError(id_)
    return id_


# -- projects ---------------------------------------------------------------
def project_dir(pid: str) -> Path:
    return PROJECTS / _safe(pid)


def create_project(title: str, rubric: dict | None, rubric_text: str, source_name: str) -> dict:
    pid = new_id("prj")
    d = project_dir(pid)
    d.mkdir(parents=True)
    p = {"id": pid, "title": title, "created": time.time(), "updated": time.time(),
         "source_name": source_name, "rubric": rubric, "versions": [], "current_version": None}
    (d / "rubric_source.txt").write_text(rubric_text or "", encoding="utf-8")
    _write_json(d / "project.json", p)
    return p


def get_project(pid: str) -> dict:
    path = project_dir(pid) / "project.json"
    if not path.exists():
        raise KeyError(pid)
    return json.loads(path.read_text(encoding="utf-8"))


def save_project(p: dict) -> dict:
    with _lock:
        p["updated"] = time.time()
        _write_json(project_dir(p["id"]) / "project.json", p)
    return p


def list_projects() -> list[dict]:
    out = []
    for d in PROJECTS.iterdir():
        f = d / "project.json"
        if f.exists():
            p = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": p["id"], "title": p["title"], "updated": p["updated"],
                        "current_version": p.get("current_version"),
                        "criteria": len((p.get("rubric") or {}).get("criteria", [])),
                        "total_marks": (p.get("rubric") or {}).get("total_marks"),
                        "demo": p.get("demo", False)})
    return sorted(out, key=lambda p: -p["updated"])


def delete_project(pid: str) -> None:
    shutil.rmtree(project_dir(pid), ignore_errors=True)
    for f in RUNS.glob("*.json"):
        try:
            if json.loads(f.read_text()).get("project_id") == pid:
                f.unlink()
                shutil.rmtree(RUNS / f.stem, ignore_errors=True)
        except Exception:
            pass


def rubric_source(pid: str) -> str:
    f = project_dir(pid) / "rubric_source.txt"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def add_checker_version(pid: str, code: str, notes: str, validation: dict, origin: str) -> dict:
    with _lock:
        p = get_project(pid)
        n = len(p["versions"]) + 1
        (project_dir(pid) / f"checker_v{n}.py").write_text(code, encoding="utf-8")
        p["versions"].append({"n": n, "created": time.time(), "notes": notes, "origin": origin,
                              "validation": validation})
        p["current_version"] = n
        save_project(p)
        return p


def get_checker(pid: str, version: int | None = None) -> str:
    p = get_project(pid)
    v = version or p.get("current_version")
    if not v:
        raise KeyError("no checker yet")
    return (project_dir(pid) / f"checker_v{v}.py").read_text(encoding="utf-8")


# -- runs -------------------------------------------------------------------
def save_run(run: dict) -> dict:
    with _lock:
        _write_json(RUNS / f"{_safe(run['id'])}.json", run)
    return run


def get_run(rid: str) -> dict:
    f = RUNS / f"{_safe(rid)}.json"
    if not f.exists():
        raise KeyError(rid)
    return json.loads(f.read_text(encoding="utf-8"))


def run_files_dir(rid: str) -> Path:
    d = RUNS / _safe(rid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_runs(pid: str) -> list[dict]:
    out = []
    for f in RUNS.glob("*.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if r.get("project_id") == pid:
            out.append({"id": r["id"], "created": r["created"], "status": r.get("status"),
                        "students": len(r.get("students", [])), "stats": r.get("stats"),
                        "checker_version": r.get("checker_version")})
    return sorted(out, key=lambda r: -r["created"])
