"""The result contract every checker script returns.

A checker builds a :class:`Report` and fills one :class:`CriterionResult`
per rubric criterion. Each criterion is used as a context manager, so a bug
in one criterion's code never wipes out the marks for the others:

    report = Report()
    with report.criterion("navigation", "Navigation", 5) as c:
        ok = c.check("Home page links to every other page", ...)
        c.score = 5 if ok else 2
    return report
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any


def _round_half(x: float) -> float:
    return round(x * 2) / 2


@dataclass
class Check:
    label: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"label": self.label, "passed": bool(self.passed), "detail": self.detail}


@dataclass
class AIReview:
    """A part of a criterion that needs human-like judgement (spelling, tone,
    content quality). The grading agent sends ``content`` to the LLM together
    with the rubric levels and ``instructions`` and uses the score it returns.
    ``provisional_score`` is used when no LLM is available."""

    instructions: str
    content: str
    provisional_score: float | None = None
    scoring_guide: str = ""

    def to_dict(self) -> dict:
        return {
            "instructions": self.instructions,
            "content": self.content,
            "provisional_score": self.provisional_score,
            "scoring_guide": self.scoring_guide,
        }


@dataclass
class CriterionResult:
    id: str
    name: str
    max_marks: float
    score: float | None = None
    level: str | None = None
    feedback: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    ai: AIReview | None = None
    error: str | None = None

    # -- helpers used by checker scripts ---------------------------------
    def check(self, label: str, passed: Any, detail: str = "") -> bool:
        """Record a pass/fail check (shown to the student) and return it."""
        passed = bool(passed)
        self.checks.append(Check(label, passed, str(detail) if detail else ""))
        return passed

    def note(self, message: str) -> None:
        """Add a line of feedback."""
        if message:
            self.feedback.append(str(message))

    def ai_review(self, instructions: str, content: str,
                  provisional_score: float | None = None,
                  scoring_guide: str = "") -> None:
        """Defer (part of) this criterion to the AI judge."""
        self.ai = AIReview(instructions, content[:60000], provisional_score, scoring_guide)

    # -- context manager: isolate failures per criterion -----------------
    def __enter__(self) -> "CriterionResult":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.error = "".join(traceback.format_exception(exc_type, exc, tb))[-3000:]
            self.score = 0.0
            self.note("Automatic check failed for this criterion; it needs manual review.")
            return True  # swallow so other criteria still run
        self.finalize()
        return False

    def finalize(self) -> None:
        if self.score is None and self.ai is None and self.error is None:
            self.error = "Checker did not set a score for this criterion."
            self.score = 0.0
        if self.score is not None:
            self.score = _round_half(max(0.0, min(float(self.max_marks), float(self.score))))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "max_marks": self.max_marks,
            "score": self.score,
            "level": self.level,
            "feedback": list(self.feedback),
            "checks": [c.to_dict() for c in self.checks],
            "ai": self.ai.to_dict() if self.ai else None,
            "error": self.error,
        }


class Report:
    def __init__(self) -> None:
        self.criteria: list[CriterionResult] = []
        self.deductions: list[dict] = []
        self.notes: list[str] = []

    def criterion(self, id: str, name: str, max_marks: float) -> CriterionResult:
        c = CriterionResult(id=id, name=name, max_marks=float(max_marks))
        self.criteria.append(c)
        return c

    def deduct(self, reason: str, marks: float) -> None:
        """A penalty outside the criteria (e.g. wrong filenames)."""
        if marks:
            self.deductions.append({"reason": str(reason), "marks": abs(float(marks))})

    def note(self, message: str) -> None:
        self.notes.append(str(message))

    def to_dict(self) -> dict:
        for c in self.criteria:
            if c.score is None and c.ai is None and c.error is None:
                c.finalize()
        crit = [c.to_dict() for c in self.criteria]

        def effective(c: dict) -> float:
            if c["score"] is not None:
                return c["score"]
            if c["ai"] and c["ai"]["provisional_score"] is not None:
                return float(c["ai"]["provisional_score"])
            return 0.0

        raw = sum(effective(c) for c in crit)
        ded = sum(d["marks"] for d in self.deductions)
        return {
            "criteria": crit,
            "deductions": list(self.deductions),
            "notes": list(self.notes),
            "raw_total": _round_half(raw),
            "deduction_total": _round_half(ded),
            "total": _round_half(max(0.0, raw - ded)),
            "max_total": sum(c["max_marks"] for c in crit),
        }
