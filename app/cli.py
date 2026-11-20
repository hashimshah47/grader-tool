"""Command-line use, no web server needed.

  # 1) rubric -> rubric.json + checker.py (tests it on your sample folder)
  python -m app.cli build Assignment_5.pdf --samples ./submissions --out ./a5

  # 2) grade a folder of submissions (folders or zips, one per student)
  python -m app.cli grade ./submissions --checker ./a5/checker.py --rubric ./a5/rubric.json --out ./a5/results
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from .agent import CheckerAgent
from .extract import find_students
from .grader import feedback_markdown, grade_student, stats, to_csv
from .llm import LLM

COLORS = {"ok": "\033[32m", "warn": "\033[33m", "error": "\033[31m", "info": ""}


def log(msg: str, level: str = "info", **_):
    print(f"{COLORS.get(level, '')}{msg}\033[0m", file=sys.stderr)


def _samples(path: str | None):
    if not path:
        return []
    tmp = Path(tempfile.mkdtemp(prefix="cli_samples_"))
    shutil.copytree(path, tmp, dirs_exist_ok=True)
    return find_students(tmp)[:3]


def cmd_build(a) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    agent = CheckerAgent(LLM(), log)
    rubric, _ = agent.parse_rubric(Path(a.rubric).name, Path(a.rubric).read_bytes())
    (out / "rubric.json").write_text(json.dumps(rubric, indent=2), encoding="utf-8")
    log(f"wrote {out / 'rubric.json'} — edit it if anything was misread, then re-run with --rubric-json", "ok")
    res = agent.build(rubric, _samples(a.samples), a.instructions or "")
    (out / "checker.py").write_text(res["code"], encoding="utf-8")
    log(f"wrote {out / 'checker.py'} ({'valid' if res['validation']['ok'] else 'HAS PROBLEMS'})",
        "ok" if res["validation"]["ok"] else "error")


def cmd_rebuild(a) -> None:
    out = Path(a.out)
    rubric = json.loads(Path(a.rubric_json).read_text(encoding="utf-8"))
    base = Path(a.checker).read_text(encoding="utf-8") if a.checker else None
    res = CheckerAgent(LLM(), log).build(rubric, _samples(a.samples), a.instructions or "", base)
    out.mkdir(parents=True, exist_ok=True)
    (out / "checker.py").write_text(res["code"], encoding="utf-8")
    log(f"wrote {out / 'checker.py'}", "ok")


def cmd_grade(a) -> None:
    rubric = json.loads(Path(a.rubric).read_text(encoding="utf-8"))
    code = Path(a.checker).read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="cli_grade_"))
    src = Path(a.submissions)
    if src.is_file():
        shutil.copy(src, tmp / src.name)
    else:
        shutil.copytree(src, tmp, dirs_exist_ok=True)
    students = find_students(tmp)
    llm = LLM()
    log(f"Grading {len(students)} submission(s)" + ("" if llm.live else " (demo mode: heuristic AI criteria)"))
    results = []
    for name, path in students:
        r = grade_student(code, name, path, rubric, llm)
        results.append(r)
        log(f"  {name}: {r['total']:g}/{r['max_total']:g}" if r["ok"] else f"  {name}: ERROR {r['error']}",
            "ok" if r["ok"] else "error")
    run = {"students": results, "stats": stats(results)}
    out = Path(a.out)
    (out / "feedback").mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    (out / "grades.csv").write_text(to_csv(run, rubric), encoding="utf-8")
    for s in results:
        safe = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in s["name"])
        (out / "feedback" / f"{safe}.md").write_text(feedback_markdown(s, rubric), encoding="utf-8")
    log(f"wrote {out}/grades.csv, results.json and feedback/*.md", "ok")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(required=True)
    b = sub.add_parser("build", help="rubric file -> rubric.json + checker.py")
    b.add_argument("rubric")
    b.add_argument("--samples", help="folder with 1-3 sample submissions to test the checker on")
    b.add_argument("--instructions", help="extra grading instructions for the agent")
    b.add_argument("--out", default="out")
    b.set_defaults(fn=cmd_build)
    r = sub.add_parser("rebuild", help="regenerate/revise a checker from an edited rubric.json")
    r.add_argument("rubric_json")
    r.add_argument("--checker", help="existing checker to revise (with --instructions)")
    r.add_argument("--samples")
    r.add_argument("--instructions")
    r.add_argument("--out", default="out")
    r.set_defaults(fn=cmd_rebuild)
    g = sub.add_parser("grade", help="grade a folder/zip of submissions")
    g.add_argument("submissions")
    g.add_argument("--checker", required=True)
    g.add_argument("--rubric", required=True)
    g.add_argument("--out", default="results")
    g.set_defaults(fn=cmd_grade)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
