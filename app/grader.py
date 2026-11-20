"""Batch grading: run the checker on every student, then let the AI judge
score the subjective parts the checker deferred with ``c.ai_review``."""
from __future__ import annotations

import csv
import io
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, prompts, storage
from .extract import listing
from .jobs import Job
from .llm import LLM, LLMError
from .sandbox import run_checker


def _half(x: float) -> float:
    return round(x * 2) / 2


def recompute(report: dict) -> dict:
    raw = 0.0
    for c in report["criteria"]:
        if c.get("score") is None:
            prov = (c.get("ai") or {}).get("provisional_score")
            c["score"] = float(prov) if prov is not None else 0.0
        raw += c["score"]
    ded = sum(d["marks"] for d in report.get("deductions", []))
    report["raw_total"] = _half(raw)
    report["deduction_total"] = _half(ded)
    report["total"] = _half(max(0.0, raw - ded))
    report["max_total"] = sum(c["max_marks"] for c in report["criteria"])
    return report


def judge(llm: LLM, crit: dict, rubric_crit: dict | None) -> dict:
    ai = crit["ai"]
    out = llm.tool_json(prompts.JUDGE_SYSTEM,
                        [{"role": "user", "content": prompts.judge_user(crit, rubric_crit, ai)}],
                        "submit_judgment", "Submit the score for this criterion.", prompts.JUDGE_SCHEMA,
                        max_tokens=3000, model=config.JUDGE_MODEL)
    out["score"] = _half(max(0.0, min(float(crit["max_marks"]), float(out.get("score", 0)))))
    return out


def apply_ai(report: dict, rubric: dict, llm: LLM) -> None:
    by_id = {c["id"]: c for c in rubric.get("criteria", [])}
    for c in report["criteria"]:
        ai = c.get("ai")
        if not ai:
            continue
        if llm.live:
            try:
                res = judge(llm, c, by_id.get(c["id"]))
                c["score"] = res["score"]
                c["level"] = res.get("level") or c.get("level")
                if res.get("feedback"):
                    c["feedback"].insert(0, res["feedback"])
                for issue in res.get("issues", [])[:12]:
                    c["feedback"].append("• " + issue)
                ai["result"] = {"mode": "ai", "model": config.JUDGE_MODEL, "issues": res.get("issues", [])}
            except LLMError as e:
                c["score"] = ai.get("provisional_score") or 0.0
                ai["result"] = {"mode": "heuristic", "reason": str(e)[:200]}
                c["feedback"].append("AI review unavailable; heuristic score used — please check.")
        else:
            if c.get("score") is None:
                c["score"] = float(ai.get("provisional_score") or 0.0)
            ai["result"] = {"mode": "heuristic", "reason": "demo mode (no API key)"}
            c["feedback"].append("Heuristic score (demo mode) — an AI/instructor review is recommended.")
        ai["content"] = (ai.get("content") or "")[:4000]


def grade_student(code: str, name: str, path: Path, rubric: dict, llm: LLM) -> dict:
    t0 = time.time()
    res = run_checker(code, path, timeout=config.CHECKER_TIMEOUT)
    rec = {"name": name, "files": listing(path, 80), "ok": bool(res.get("ok"))}
    if not res.get("ok"):
        rec.update(error=res.get("error"), traceback=res.get("traceback", "")[-3000:], total=None)
    else:
        rep = res["report"]
        apply_ai(rep, rubric, llm)
        recompute(rep)
        rec.update(report=rep, total=rep["total"], max_total=rep["max_total"],
                   needs_review=any(c.get("error") for c in rep["criteria"]))
    rec["seconds"] = round(time.time() - t0, 2)
    return rec


def stats(students: list[dict]) -> dict:
    totals = [s["total"] for s in students if s.get("total") is not None]
    out = {"count": len(students), "graded": len(totals), "failed": len(students) - len(totals)}
    if totals:
        out.update(mean=round(statistics.mean(totals), 2), median=statistics.median(totals),
                   min=min(totals), max=max(totals))
    per = {}
    for s in students:
        for c in (s.get("report") or {}).get("criteria", []):
            per.setdefault(c["id"], []).append(c["score"] or 0)
    out["criteria_mean"] = {k: round(statistics.mean(v), 2) for k, v in per.items()}
    return out


def grade_all(job: Job, project: dict, code: str, version: int, students: list[tuple[str, Path]],
              llm: LLM, run_id: str) -> dict:
    rubric = project["rubric"]
    run = {"id": run_id, "project_id": project["id"], "project_title": project["title"],
           "checker_version": version, "created": time.time(), "status": "running",
           "llm_mode": "ai" if llm.live else "heuristic", "students": []}
    storage.save_run(run)
    job.set_progress(0, len(students))
    job.log(f"Grading {len(students)} submission(s) with checker v{version}"
            + ("" if llm.live else " (demo mode: heuristic scores for AI criteria)") + "…")
    results: list[dict | None] = [None] * len(students)
    done = 0

    def work(i: int) -> None:
        nonlocal done
        name, path = students[i]
        rec = grade_student(code, name, path, rubric, llm)
        results[i] = rec
        done += 1
        job.set_progress(done, len(students))
        if rec["ok"]:
            job.log(f"✓ {name}: {rec['total']:g}/{rec['max_total']:g}", "ok")
        else:
            job.log(f"✗ {name}: {rec['error']}", "error")

    with ThreadPoolExecutor(max_workers=max(1, config.GRADE_CONCURRENCY)) as pool:
        list(pool.map(work, range(len(students))))
    run["students"] = [r for r in results if r]
    run["students"].sort(key=lambda s: s["name"].lower())
    run["stats"] = stats(run["students"])
    run["status"] = "done"
    storage.save_run(run)
    st = run["stats"]
    if st.get("graded"):
        job.log(f"Done. Average {st['mean']:g}, median {st['median']:g}, range {st['min']:g}–{st['max']:g}.", "ok")
    return {"run_id": run_id}


def override(run: dict, student_index: int, criterion_id: str, score: float | None, comment: str) -> dict:
    s = run["students"][student_index]
    for c in s["report"]["criteria"]:
        if c["id"] == criterion_id:
            if score is not None:
                c.setdefault("auto_score", c["score"])
                c["score"] = _half(max(0.0, min(c["max_marks"], float(score))))
                c["overridden"] = True
            if comment:
                c["feedback"].append(f"Instructor: {comment}")
    recompute(s["report"])
    s["total"] = s["report"]["total"]
    run["stats"] = stats(run["students"])
    return run


def to_csv(run: dict, rubric: dict) -> str:
    crit = [c["id"] for c in rubric.get("criteria", [])]
    names = {c["id"]: c["name"] for c in rubric.get("criteria", [])}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Student"] + [f"{names[c]} ({c})" for c in crit] + ["Deductions", "Total", "Out of", "Status"])
    for s in run["students"]:
        if not s.get("ok"):
            w.writerow([s["name"]] + [""] * len(crit) + ["", "", "", f"ERROR: {s.get('error')}"])
            continue
        rep = s["report"]
        by = {c["id"]: c for c in rep["criteria"]}
        w.writerow([s["name"]] + [by.get(c, {}).get("score", "") for c in crit]
                   + [rep["deduction_total"], rep["total"], rep["max_total"],
                      "needs review" if s.get("needs_review") else "ok"])
    return buf.getvalue()


def feedback_markdown(student: dict, rubric: dict) -> str:
    lines = [f"# {rubric.get('title', 'Assignment')} — feedback for {student['name']}", ""]
    if not student.get("ok"):
        return "\n".join(lines + ["The automatic checker could not grade this submission:", "",
                                  f"    {student.get('error')}", ""])
    rep = student["report"]
    lines += [f"**Total: {rep['total']:g} / {rep['max_total']:g}**", ""]
    for c in rep["criteria"]:
        lines.append(f"## {c['name']} — {c['score']:g} / {c['max_marks']:g}"
                     + (f" ({c['level']})" if c.get("level") else ""))
        for ch in c["checks"]:
            lines.append(f"- {'✅' if ch['passed'] else '❌'} {ch['label']}" + (f" — {ch['detail']}" if ch["detail"] else ""))
        for f in c["feedback"]:
            lines.append(f"- {f}")
        lines.append("")
    if rep["deductions"]:
        lines.append("## Deductions")
        lines += [f"- −{d['marks']:g}: {d['reason']}" for d in rep["deductions"]]
        lines.append("")
    if rep.get("notes"):
        lines.append("## Notes")
        lines += [f"- {n}" for n in rep["notes"]]
    return "\n".join(lines) + "\n"
