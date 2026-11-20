"""FastAPI app: REST API + the single-page web UI."""
from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, jobs, storage
from .agent import CheckerAgent, normalise_rubric
from .extract import find_students, safe_extract
from .grader import feedback_markdown, grade_all, override, to_csv
from .llm import LLM
from .sandbox import static_check

app = FastAPI(title="Rubric-to-Checker: AI assignment grader")
STATIC = config.ROOT / "static"


def _llm() -> LLM:
    return LLM()


def _404(fn, *a):
    try:
        return fn(*a)
    except KeyError:
        raise HTTPException(404, "Not found")


def _clean_rel(name: str) -> str:
    name = (name or "file").replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    parts = [re.sub(r"[^\w.\- ()&,'+@]", "_", p) for p in parts]
    return "/".join(parts) or "file"


async def _save_uploads(files: list[UploadFile], paths: list[str], dest: Path) -> int:
    """Save uploaded files (keeping folder structure) and unzip archives."""
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    for i, f in enumerate(files):
        rel = _clean_rel(paths[i] if i < len(paths) and paths[i] else f.filename)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = await f.read()
        total += len(data)
        if total > config.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"Upload larger than {config.MAX_UPLOAD_MB} MB")
        target.write_bytes(data)
    return total


# ---------------------------------------------------------------- status
@app.get("/api/status")
def status():
    llm = _llm()
    return {"mode": "live" if llm.live else "demo", "model": config.MODEL if llm.live else None,
            "judge_model": config.JUDGE_MODEL if llm.live else None,
            "max_fix_attempts": config.MAX_FIX_ATTEMPTS}


@app.get("/api/jobs/{jid}")
def job_status(jid: str, since: int = 0):
    try:
        return jobs.get(jid).to_dict(since)
    except KeyError:
        raise HTTPException(404, "Job not found")


# ---------------------------------------------------------------- projects
@app.get("/api/projects")
def projects():
    return storage.list_projects()


@app.get("/api/projects/{pid}")
def project(pid: str):
    p = _404(storage.get_project, pid)
    p["runs"] = storage.list_runs(pid)
    return p


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    _404(storage.get_project, pid)
    storage.delete_project(pid)
    return {"ok": True}


@app.post("/api/projects")
async def create_project(rubric: UploadFile = File(...)):
    """Upload a rubric (PDF/DOCX/TXT/MD/HTML); the agent structures it."""
    data = await rubric.read()
    filename = rubric.filename or "rubric.txt"
    if not data:
        raise HTTPException(400, "Empty file")

    def work(job: jobs.Job) -> dict:
        agent = CheckerAgent(_llm(), job.log)
        parsed, text = agent.parse_rubric(filename, data)
        p = storage.create_project(parsed.get("title") or Path(filename).stem, parsed, text, filename)
        job.log("Rubric saved. Review it, then generate the checker.", "ok")
        return {"project_id": p["id"]}

    return {"job_id": jobs.start("parse", work).id}


class RubricBody(BaseModel):
    rubric: dict


@app.put("/api/projects/{pid}/rubric")
def update_rubric(pid: str, body: RubricBody):
    p = _404(storage.get_project, pid)
    r = normalise_rubric(body.rubric)
    if not r.get("criteria"):
        raise HTTPException(400, "Rubric needs at least one criterion")
    p["rubric"] = r
    p["title"] = r.get("title") or p["title"]
    storage.save_project(p)
    return p


@app.post("/api/projects/{pid}/generate")
async def generate(pid: str, instructions: str = Form(""), revise: bool = Form(False),
                   files: list[UploadFile] = File(default=[]), paths: list[str] = Form(default=[])):
    """Generate (or revise) the checker. Optional sample submissions are used to test it."""
    p = _404(storage.get_project, pid)
    if not p.get("rubric"):
        raise HTTPException(400, "Project has no rubric")
    sample_dir = storage.project_dir(pid) / "samples"
    if files:
        shutil.rmtree(sample_dir, ignore_errors=True)
        await _save_uploads(files, paths, sample_dir)
    base = storage.get_checker(pid) if (revise and p.get("current_version")) else None

    def work(job: jobs.Job) -> dict:
        samples = []
        if sample_dir.exists():
            tmp = Path(tempfile.mkdtemp(prefix="samples_"))
            shutil.copytree(sample_dir, tmp, dirs_exist_ok=True)
            samples = find_students(tmp)[:3]
            if samples:
                job.log(f"Testing against {len(samples)} sample submission(s): "
                        + ", ".join(n for n, _ in samples))
        agent = CheckerAgent(_llm(), job.log)
        out = agent.build(p["rubric"], samples, instructions, base)
        v = out["validation"]
        slim = {"ok": v["ok"], "problems": v["problems"][:20],
                "runs": [{k: r.get(k) for k in ("name", "ok", "total", "max_total", "error")} for r in v["runs"]]}
        storage.add_checker_version(pid, out["code"], out["notes"], slim | {"attempts": out["attempts"]},
                                    out["origin"])
        return {"project_id": pid, "ok": v["ok"]}

    return {"job_id": jobs.start("generate", work).id}


@app.get("/api/projects/{pid}/checker", response_class=PlainTextResponse)
def get_checker(pid: str, version: int | None = None):
    return _404(storage.get_checker, pid, version)


class CodeBody(BaseModel):
    code: str
    notes: str = "Edited by instructor"


@app.put("/api/projects/{pid}/checker")
def save_checker(pid: str, body: CodeBody):
    p = _404(storage.get_project, pid)
    agent = CheckerAgent(_llm())
    problems = static_check(body.code)
    if problems:
        return JSONResponse({"ok": False, "problems": problems}, status_code=422)
    v = agent.validate(body.code, p["rubric"], [])
    slim = {"ok": v["ok"], "problems": v["problems"][:20],
            "runs": [{k: r.get(k) for k in ("name", "ok", "total", "max_total", "error")} for r in v["runs"]]}
    p = storage.add_checker_version(pid, body.code, body.notes, slim, "edited")
    return {"ok": v["ok"], "problems": v["problems"], "version": p["current_version"]}


@app.post("/api/projects/{pid}/use_version/{n}")
def use_version(pid: str, n: int):
    p = _404(storage.get_project, pid)
    if not any(v["n"] == n for v in p["versions"]):
        raise HTTPException(404, "No such version")
    p["current_version"] = n
    return storage.save_project(p)


@app.get("/api/projects/{pid}/checker.py")
def download_checker(pid: str):
    code = _404(storage.get_checker, pid)
    return Response(code, media_type="text/x-python",
                    headers={"Content-Disposition": f'attachment; filename="checker_{pid}.py"'})


# ---------------------------------------------------------------- grading
def _start_grading(pid: str, src_dir: Path) -> str:
    p = _404(storage.get_project, pid)
    if not p.get("current_version"):
        raise HTTPException(400, "Generate a checker first")
    code = storage.get_checker(pid)
    version = p["current_version"]
    rid = storage.new_id("run")

    def work(job: jobs.Job) -> dict:
        students = find_students(src_dir)
        if not students:
            raise ValueError("No submissions found in the upload")
        return grade_all(job, p, code, version, students, _llm(), rid)

    return jobs.start("grade", work).id


@app.post("/api/projects/{pid}/grade")
async def grade(pid: str, files: list[UploadFile] = File(...), paths: list[str] = Form(default=[])):
    """Upload a folder (webkitdirectory) or zip(s) of student submissions."""
    _404(storage.get_project, pid)
    dest = Path(tempfile.mkdtemp(prefix="subs_"))
    await _save_uploads(files, paths, dest)
    return {"job_id": _start_grading(pid, dest)}


@app.get("/api/runs/{rid}")
def get_run(rid: str):
    return _404(storage.get_run, rid)


class OverrideBody(BaseModel):
    student: int
    criterion: str
    score: float | None = None
    comment: str = ""


@app.post("/api/runs/{rid}/override")
def override_score(rid: str, body: OverrideBody):
    run = _404(storage.get_run, rid)
    try:
        run = override(run, body.student, body.criterion, body.score, body.comment)
    except (IndexError, KeyError):
        raise HTTPException(400, "Bad student/criterion")
    storage.save_run(run)
    return run


@app.get("/api/runs/{rid}/grades.csv")
def run_csv(rid: str):
    run = _404(storage.get_run, rid)
    p = _404(storage.get_project, run["project_id"])
    return Response(to_csv(run, p["rubric"]), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="grades_{rid}.csv"'})


@app.get("/api/runs/{rid}/feedback.zip")
def run_feedback(rid: str):
    run = _404(storage.get_run, rid)
    p = _404(storage.get_project, run["project_id"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for s in run["students"]:
            z.writestr(f"{_clean_rel(s['name']).replace('/', '_')}.md", feedback_markdown(s, p["rubric"]))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="feedback_{rid}.zip"'})


# ---------------------------------------------------------------- demo
@app.post("/api/demo")
def demo():
    """Create a project from the bundled Assignment 5 rubric (no API key needed)."""
    rubric = json.loads((config.EXAMPLES / "assignment5_rubric.json").read_text(encoding="utf-8"))
    p = storage.create_project(rubric["title"], rubric, "", "Assignment_5.pdf (bundled example)")
    p["demo"] = True
    storage.save_project(p)
    code = (config.EXAMPLES / "assignment5_checker.py").read_text(encoding="utf-8")
    v = CheckerAgent(_llm()).validate(code, rubric, [])
    storage.add_checker_version(p["id"], code, "Bundled example checker",
                                {"ok": v["ok"], "problems": v["problems"],
                                 "runs": [{k: r.get(k) for k in ("name", "ok", "total", "max_total")} for r in v["runs"]]},
                                "example")
    return {"project_id": p["id"]}


@app.post("/api/projects/{pid}/grade_samples")
def grade_samples(pid: str):
    """Grade the bundled sample class (3 students) — for the demo."""
    src = config.EXAMPLES / "submissions"
    if not src.exists():
        raise HTTPException(404, "Run examples/make_samples.py first")
    dest = Path(tempfile.mkdtemp(prefix="subs_"))
    shutil.copytree(src, dest, dirs_exist_ok=True)
    return {"job_id": _start_grading(pid, dest)}


@app.get("/api/demo/class_submissions.zip")
def demo_zip():
    f = config.EXAMPLES / "class_submissions.zip"
    if not f.exists():
        raise HTTPException(404, "Run examples/make_samples.py first")
    return FileResponse(f, filename="class_submissions.zip")


@app.get("/api/demo/rubric.pdf")
def demo_pdf():
    f = config.EXAMPLES / "Assignment_5.pdf"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, filename="Assignment_5.pdf")


# ---------------------------------------------------------------- UI
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
