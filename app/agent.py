"""The checker-building agent.

    rubric file ──► parse (LLM, structured JSON)
                       │
                       ▼
                 generate checker (LLM writes Python using gradekit)
                       │
           ┌──────────►▼
           │     validate: AST safety check → run on an empty submission →
           │               run on sample submissions → check the result contract
           │           │ problems?
           └─── fix ◄──┘ (LLM gets the tracebacks / contract violations)
                       │ ok
                       ▼
                 self-review (LLM compares sample results with the rubric)
                       │ issues? → one more fix + validate round
                       ▼
                 save checker version
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Callable

from . import config, prompts
from .extract import listing, rubric_text
from .llm import LLM, LLMError, extract_python, pdf_block
from .sandbox import run_checker, static_check

Log = Callable[..., None]


def _noop(*_a, **_k):
    return None


def _example_rubric() -> dict:
    return json.loads((config.EXAMPLES / "assignment5_rubric.json").read_text(encoding="utf-8"))


def _example_checker() -> str:
    return (config.EXAMPLES / "assignment5_checker.py").read_text(encoding="utf-8")


def is_example_rubric(rubric: dict) -> bool:
    ex = {c["id"] for c in _example_rubric()["criteria"]}
    return {c["id"] for c in rubric.get("criteria", [])} == ex


def normalise_rubric(r: dict) -> dict:
    """Fill defaults and make ids unique/valid so later steps can rely on them."""
    seen = set()
    for i, c in enumerate(r.get("criteria", [])):
        cid = "".join(ch if ch.isalnum() else "_" for ch in (c.get("id") or c.get("name") or f"c{i + 1}").lower()).strip("_")
        cid = cid or f"criterion_{i + 1}"
        while cid in seen:
            cid += "_2"
        seen.add(cid)
        c["id"] = cid
        c["max_marks"] = float(c.get("max_marks") or 0)
        c.setdefault("levels", [])
        c.setdefault("grading_mode", "automated")
        c.setdefault("how_to_check", "")
        c.setdefault("description", "")
    r.setdefault("required_files", [])
    r.setdefault("requirements", [])
    r.setdefault("deductions", [])
    r.setdefault("notes", "")
    if not r.get("total_marks"):
        r["total_marks"] = sum(c["max_marks"] for c in r.get("criteria", []))
    return r


class CheckerAgent:
    def __init__(self, llm: LLM | None = None, log: Log = _noop) -> None:
        self.llm = llm or LLM()
        self.log = log

    # ------------------------------------------------------------------ parse
    def parse_rubric(self, filename: str, data: bytes) -> tuple[dict, str]:
        self.log(f"Reading {filename}…")
        text = rubric_text(filename, data)
        self.log(f"Extracted {len(text):,} characters of text.")
        if not self.llm.live:
            if "mybio" in text.lower() and "image map" in text.lower():
                self.log("Demo mode: recognised the bundled Assignment 5 rubric.", "warn")
                return _example_rubric(), text
            raise LLMError("Demo mode can only read the bundled Assignment 5 rubric. "
                           "Set ANTHROPIC_API_KEY to parse other rubrics.")
        self.log(f"Asking {self.llm.model} to structure the rubric…")
        content: list[dict] = []
        if filename.lower().endswith(".pdf") and len(data) < 30 * 1024 * 1024:
            content.append(pdf_block(data))  # lets the model see the rubric table layout
        content.append({"type": "text", "text":
                        f"<extracted_text file=\"{filename}\">\n{text[:120000]}\n</extracted_text>\n\n"
                        "Structure this assignment rubric by calling submit_rubric."})
        rubric = self.llm.tool_json(prompts.RUBRIC_SYSTEM, [{"role": "user", "content": content}],
                                    "submit_rubric", "Submit the structured rubric.", prompts.RUBRIC_SCHEMA)
        rubric = normalise_rubric(rubric)
        self.log(f"Found {len(rubric['criteria'])} criteria worth {rubric['total_marks']:g} marks.", "ok")
        return rubric, text

    # --------------------------------------------------------------- validate
    def validate(self, code: str, rubric: dict, samples: list[tuple[str, Path]]) -> dict:
        problems = static_check(code)
        runs: list[dict] = []
        if problems:
            return {"ok": False, "problems": problems, "runs": runs}
        expected = {c["id"]: c for c in rubric["criteria"]}
        with tempfile.TemporaryDirectory(prefix="empty_sub_") as empty:
            targets = [("(empty submission)", Path(empty))] + samples[:3]
            for name, path in targets:
                res = run_checker(code, path, timeout=config.CHECKER_TIMEOUT)
                run = {"name": name, "ok": res.get("ok", False)}
                if not res.get("ok"):
                    msg = res.get("error", "failed")
                    if res.get("problems"):
                        msg += ": " + "; ".join(res["problems"])
                    problems.append(f"Running on {name} crashed: {msg}\n{res.get('traceback', '')[-1500:]}")
                    run["error"] = msg
                    runs.append(run)
                    continue
                rep = res["report"]
                run.update(total=rep["total"], max_total=rep["max_total"], report=rep,
                           duration=res.get("duration"))
                runs.append(run)
                got = {c["id"]: c for c in rep["criteria"]}
                for cid in expected:
                    if cid not in got:
                        problems.append(f"Criterion '{cid}' is missing from the report (on {name}).")
                for cid in got:
                    if cid not in expected:
                        problems.append(f"Report contains unknown criterion id '{cid}'; "
                                        f"use only: {', '.join(expected)}.")
                for cid, c in got.items():
                    if cid in expected and abs(c["max_marks"] - expected[cid]["max_marks"]) > 1e-6:
                        problems.append(f"Criterion '{cid}' max_marks is {c['max_marks']:g} but the rubric "
                                        f"says {expected[cid]['max_marks']:g}.")
                    if c.get("error"):
                        problems.append(f"Criterion '{cid}' raised an exception on {name}:\n{c['error'][-1500:]}")
        # de-duplicate (the same bug usually shows up on every run)
        seen, uniq = set(), []
        for p in problems:
            key = p[:200]
            if key not in seen:
                seen.add(key)
                uniq.append(p)
        return {"ok": not uniq, "problems": uniq, "runs": runs}

    # ------------------------------------------------------------------ build
    def build(self, rubric: dict, samples: list[tuple[str, Path]] | None = None,
              instructions: str = "", base_code: str | None = None) -> dict:
        samples = samples or []
        if not self.llm.live:
            if not is_example_rubric(rubric):
                raise LLMError("Demo mode only includes a checker for the bundled Assignment 5 rubric. "
                               "Set ANTHROPIC_API_KEY to generate checkers for other rubrics.")
            self.log("Demo mode: using the pre-generated Assignment 5 checker.", "warn")
            code = _example_checker()
            v = self._validate_logged(code, rubric, samples)
            return {"code": code, "validation": v, "attempts": 0, "notes": "Demo checker", "origin": "demo"}

        system = prompts.checker_system()
        rubric_json = json.dumps(rubric, indent=2, ensure_ascii=False)
        sample_listing = ""
        if samples:
            sample_listing = "\n\n".join(f"[{n}]\n{listing(p, 40)}" for n, p in samples[:2])
        first = prompts.checker_user(rubric_json, instructions if not base_code else "", sample_listing)
        messages: list[dict] = [{"role": "user", "content": first}]
        if base_code:
            messages += [{"role": "assistant", "content": f"```python\n{base_code}\n```"},
                         {"role": "user", "content": "Revise this checker according to the instructor's "
                                                     f"instructions below. Keep everything else the same.\n\n"
                                                     f"<instructor_instructions>\n{instructions}\n"
                                                     "</instructor_instructions>\n\nReturn the complete file "
                                                     "in a single ```python block."}]
            self.log("Revising the current checker with your instructions…")
        else:
            self.log(f"Writing a checker for {len(rubric['criteria'])} criteria…")

        code = extract_python(self.llm.text(system, messages))
        self.log(f"Draft ready ({len(code.splitlines())} lines). Testing it…")
        attempts = 0
        v = self._validate_logged(code, rubric, samples)
        while not v["ok"] and attempts < config.MAX_FIX_ATTEMPTS:
            attempts += 1
            self.log(f"Fix attempt {attempts}/{config.MAX_FIX_ATTEMPTS}: sending "
                     f"{len(v['problems'])} problem(s) back to the model…", "warn")
            messages += [{"role": "assistant", "content": f"```python\n{code}```"},
                         {"role": "user", "content": prompts.fix_user(v["problems"])}]
            code = extract_python(self.llm.text(system, messages))
            v = self._validate_logged(code, rubric, samples)

        if v["ok"] and samples and config.REVIEW_PASS:
            code, v, messages = self._review(system, messages, code, v, rubric, samples)

        if v["ok"]:
            self.log("Checker passed all tests.", "ok")
        else:
            self.log("Checker still has problems; saved anyway so you can edit it.", "error")
        return {"code": code, "validation": v, "attempts": attempts,
                "notes": instructions.strip()[:300] if instructions else "Generated from rubric",
                "origin": "revised" if base_code else "generated"}

    def _review(self, system, messages, code, v, rubric, samples):
        self.log("Self-review: comparing sample results with the rubric…")
        summary = self._summarise_runs(v["runs"], samples)
        review_msgs = messages + [{"role": "assistant", "content": f"```python\n{code}```"},
                                  {"role": "user", "content": prompts.review_user(summary)}]
        try:
            review = self.llm.tool_json(system, review_msgs, "submit_review",
                                        "Report whether the grading results are correct.",
                                        prompts.REVIEW_SCHEMA, max_tokens=3000)
        except LLMError as e:
            self.log(f"Review skipped: {e}", "warn")
            return code, v, messages
        issues = [i for i in review.get("issues", []) if i.strip()]
        if review.get("looks_correct") or not issues:
            self.log("Self-review found no grading bugs.", "ok")
            return code, v, messages
        for i in issues[:6]:
            self.log(f"Review: {i}", "warn")
        msgs2 = messages + [{"role": "assistant", "content": f"```python\n{code}```"},
                            {"role": "user", "content": prompts.fix_user(
                                ["Grading review found: " + i for i in issues])}]
        code2 = extract_python(self.llm.text(system, msgs2))
        v2 = self._validate_logged(code2, rubric, samples)
        if v2["ok"]:
            self.log("Applied review fixes.", "ok")
            return code2, v2, msgs2
        self.log("Review fixes broke the checker; keeping the previous version.", "warn")
        return code, v, messages

    def _validate_logged(self, code, rubric, samples) -> dict:
        v = self.validate(code, rubric, samples)
        for r in v["runs"]:
            if r.get("ok"):
                self.log(f"  ✓ {r['name']}: {r['total']:g}/{r['max_total']:g}", "info")
            else:
                self.log(f"  ✗ {r['name']}: {r.get('error', 'failed')[:200]}", "warn")
        if v["problems"] and not v["runs"]:
            for p in v["problems"][:5]:
                self.log(f"  ✗ {p[:200]}", "warn")
        return v

    @staticmethod
    def _summarise_runs(runs: list[dict], samples: list[tuple[str, Path]]) -> str:
        paths = dict(samples)
        out = []
        for r in runs:
            if not r.get("ok") or r["name"].startswith("("):
                continue
            rep = r["report"]
            lines = [f"## {r['name']} — {rep['total']:g}/{rep['max_total']:g}"]
            if r["name"] in paths:
                lines.append("Files:\n" + listing(paths[r["name"]], 30))
            for c in rep["criteria"]:
                score = c["score"] if c["score"] is not None else (c["ai"] or {}).get("provisional_score")
                lines.append(f"- {c['id']}: {score}/{c['max_marks']:g} ({c.get('level') or ''})")
                for ch in c["checks"]:
                    if not ch["passed"]:
                        lines.append(f"    ✗ {ch['label']} {ch['detail']}")
                for f in c["feedback"][:6]:
                    lines.append(f"    • {f}")
            for d in rep["deductions"]:
                lines.append(f"- deduction: -{d['marks']:g} {d['reason']}")
            out.append("\n".join(lines))
        return "\n\n".join(out)[:30000]
