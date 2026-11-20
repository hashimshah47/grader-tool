"""End-to-end tests. Run: pytest -q"""
import json
import shutil
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


@pytest.fixture(autouse=True, scope="session")
def _samples():
    if not (EX / "submissions").exists():
        import runpy
        runpy.run_path(str(EX / "make_samples.py"), run_name="__main__")


def checker_code():
    return (EX / "assignment5_checker.py").read_text()


def rubric():
    return json.loads((EX / "assignment5_rubric.json").read_text())


# ------------------------------------------------------------------ sandbox
def test_static_check_blocks_dangerous_code():
    from app.sandbox import static_check
    bad = "import os\nfrom subprocess import run\ndef grade(sub):\n    open('x','w')\n    eval('1')\n    ().__class__\n"
    problems = " ".join(static_check(bad))
    for word in ("os", "subprocess", "open", "eval", "__class__"):
        assert word in problems
    assert static_check(checker_code()) == []


def test_sandbox_timeout_and_crash():
    from app.sandbox import run_checker
    loop = "from gradekit import Report\ndef grade(sub):\n    while True:\n        pass\n"
    r = run_checker(loop, EX / "submissions/sam_patel", timeout=3)
    assert not r["ok"] and "timed out" in r["error"]
    crash = "def grade(sub):\n    return 1/0\n"
    r = run_checker(crash, EX / "submissions/sam_patel")
    assert not r["ok"] and "ZeroDivisionError" in r["error"]


def test_criterion_errors_are_isolated():
    from app.sandbox import run_checker
    code = ("from gradekit import Report\n"
            "def grade(sub):\n    r = Report()\n"
            "    with r.criterion('a', 'A', 5) as c:\n        c.score = 1/0\n"
            "    with r.criterion('b', 'B', 5) as c:\n        c.score = 4\n    return r\n")
    r = run_checker(code, EX / "submissions/sam_patel")
    crit = {c["id"]: c for c in r["report"]["criteria"]}
    assert crit["a"]["error"] and crit["a"]["score"] == 0
    assert crit["b"]["score"] == 4 and r["report"]["total"] == 4


# ------------------------------------------------------------------ checker
@pytest.mark.parametrize("student,lo,hi", [("alex_rivera", 48, 50), ("jordan_lee", 20, 34), ("sam_patel", 5, 16)])
def test_reference_checker_ranks_samples(student, lo, hi):
    from app.sandbox import run_checker
    from app.grader import apply_ai, recompute
    from app.llm import LLM
    r = run_checker(checker_code(), EX / "submissions" / student)
    assert r["ok"], r
    rep = r["report"]
    apply_ai(rep, rubric(), LLM(api_key=""))
    recompute(rep)
    assert lo <= rep["total"] <= hi, (student, rep["total"])


def test_partial_submission_details():
    from app.sandbox import run_checker
    rep = run_checker(checker_code(), EX / "submissions/jordan_lee")["report"]
    assert any("MyBio.html" in d["reason"] for d in rep["deductions"])
    nav = next(c for c in rep["criteria"] if c["id"] == "navigation")
    assert any("hobbys.html" in f for f in nav["feedback"])
    imgs = next(c for c in rep["criteria"] if c["id"] == "images")
    assert imgs["score"] <= 5


# ------------------------------------------------------------------ agent loop
class FakeLLM:
    """Pretends to be Claude: first draft is buggy, the fix is correct."""
    live = True
    model = "fake"

    def __init__(self):
        self.text_calls = 0
        self.messages_seen = []

    def text(self, system, messages, max_tokens=0, model=None):
        self.text_calls += 1
        self.messages_seen.append(messages)
        if self.text_calls == 1:
            buggy = checker_code().replace('with report.criterion("navigation"', 'with report.criterion("nav"')
            buggy = buggy.replace("home_missing = 3", "home_missing = undefined_name")
            return f"```python\n{buggy}\n```"
        return f"```python\n{checker_code()}\n```"

    def tool_json(self, system, messages, tool_name, *a, **k):
        if tool_name == "submit_rubric":
            return rubric()
        if tool_name == "submit_review":
            return {"looks_correct": True, "issues": []}
        if tool_name == "submit_judgment":
            return {"issues": ["'realy' -> 'really'"], "score": 4, "level": "Accomplished", "feedback": "Nearly perfect."}
        raise AssertionError(tool_name)


def test_agent_fix_loop_repairs_checker(tmp_path):
    from app.agent import CheckerAgent
    llm = FakeLLM()
    logs = []
    agent = CheckerAgent(llm, lambda m, *a, **k: logs.append(m))
    samples = [("jordan_lee", EX / "submissions/jordan_lee")]
    out = agent.build(rubric(), samples)
    assert out["validation"]["ok"], out["validation"]["problems"]
    assert out["attempts"] == 1 and llm.text_calls == 2
    fix_prompt = llm.messages_seen[1][-1]["content"]
    assert "missing from the report" in fix_prompt and "unknown criterion id 'nav'" in fix_prompt


def test_parse_rubric_demo_mode():
    from app.agent import CheckerAgent
    from app.llm import LLM
    r, text = CheckerAgent(LLM(api_key="")).parse_rubric("Assignment_5.pdf", (EX / "Assignment_5.pdf").read_bytes())
    assert r["total_marks"] == 50 and len(r["criteria"]) == 5


# ------------------------------------------------------------------ uploads
def test_find_students_handles_class_zip(tmp_path):
    from app.extract import find_students, safe_extract
    shutil.copy(EX / "class_submissions.zip", tmp_path / "class.zip")
    students = find_students(tmp_path)
    assert sorted(n for n, _ in students) == ["alex_rivera", "jordan_lee", "sam_patel"]


def test_find_students_nested_zip_per_student(tmp_path):
    import zipfile
    from app.extract import find_students
    for s in ("alex_rivera", "sam_patel"):
        d = tmp_path / "export" / f"{s} - Nov 3"
        d.mkdir(parents=True)
        with zipfile.ZipFile(d / "mybio.zip", "w") as z:
            for f in (EX / "submissions" / s).rglob("*"):
                if f.is_file():
                    z.write(f, "mybio/" + f.relative_to(EX / "submissions" / s).as_posix())
    students = find_students(tmp_path)
    assert len(students) == 2
    assert all((p / "mybio.html").exists() for _, p in students)


# ------------------------------------------------------------------ API
def test_api_demo_flow():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get("/api/status").json()["mode"] in ("demo", "live")
    pid = c.post("/api/demo").json()["project_id"]
    jid = c.post(f"/api/projects/{pid}/grade_samples").json()["job_id"]
    for _ in range(100):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            break
        time.sleep(0.2)
    assert j["status"] == "done", j
    rid = j["result"]["run_id"]
    run = c.get(f"/api/runs/{rid}").json()
    assert run["stats"]["graded"] == 3
    csv = c.get(f"/api/runs/{rid}/grades.csv").text
    assert "alex_rivera" in csv and "Total" in csv
    idx = [s["name"] for s in run["students"]].index("sam_patel")
    run2 = c.post(f"/api/runs/{rid}/override", json={"student": idx, "criterion": "content", "score": 5,
                                                     "comment": "Generous"}).json()
    assert next(x for x in run2["students"][idx]["report"]["criteria"] if x["id"] == "content")["score"] == 5
    assert c.get(f"/api/runs/{rid}/feedback.zip").status_code == 200
    # editing the checker re-validates it
    bad = c.put(f"/api/projects/{pid}/checker", json={"code": "import os\ndef grade(s): pass"})
    assert bad.status_code == 422
    c.delete(f"/api/projects/{pid}")


def _wait(c, jid):
    for _ in range(150):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.2)
    raise AssertionError("job timed out")


def test_api_upload_rubric_generate_and_grade_folder():
    """Full UI flow in demo mode: PDF upload -> parse -> generate (with samples) -> grade an uploaded folder."""
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    pdf = (EX / "Assignment_5.pdf").read_bytes()
    j = _wait(c, c.post("/api/projects", files={"rubric": ("Assignment_5.pdf", pdf, "application/pdf")}).json()["job_id"])
    assert j["status"] == "done", j
    pid = j["result"]["project_id"]
    # samples uploaded as a folder (webkitdirectory style relative paths)
    files, paths = [], []
    for f in (EX / "submissions/jordan_lee").rglob("*"):
        rel = "samples/jordan_lee/" + f.relative_to(EX / "submissions/jordan_lee").as_posix()
        files.append(("files", (rel, f.read_bytes())))
        paths.append(("paths", rel))
    r = c.post(f"/api/projects/{pid}/generate", data={"instructions": "", "paths": [p for _, p in paths]}, files=files)
    j = _wait(c, r.json()["job_id"])
    assert j["status"] == "done", j
    assert any("jordan_lee" in e["message"] for e in j["events"])
    p = c.get(f"/api/projects/{pid}").json()
    assert p["current_version"] == 1 and p["versions"][0]["validation"]["ok"]
    # grade the class zip
    z = (EX / "class_submissions.zip").read_bytes()
    j = _wait(c, c.post(f"/api/projects/{pid}/grade", files=[("files", ("class.zip", z))]).json()["job_id"])
    assert j["status"] == "done", j
    run = c.get(f"/api/runs/{j['result']['run_id']}").json()
    assert [s["name"] for s in run["students"]] == ["alex_rivera", "jordan_lee", "sam_patel"]
    c.delete(f"/api/projects/{pid}")
