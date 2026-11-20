"""gradekit — helpers for grading HTML/CSS/JavaScript assignments.

Generated checker scripts import from here, so they stay short and only do
the rubric-specific logic. See API.md for the reference given to the AI.
"""
from .css import CssDoc, CssRule, parse_declarations
from .html import HtmlDoc, HtmlIssue
from .js import JsDoc
from .report import CriterionResult, Report
from .submission import FileMatch, LinkCheck, Submission
from .text import is_descriptive_alt, sentences, spelling_candidates, word_count, words

__all__ = [
    "Submission", "Report", "CriterionResult", "HtmlDoc", "HtmlIssue", "CssDoc", "CssRule",
    "JsDoc", "FileMatch", "LinkCheck", "parse_declarations", "is_descriptive_alt",
    "spelling_candidates", "word_count", "words", "sentences", "band",
]


def band(value: float, table: list[tuple[float, float]], default: float = 0.0) -> float:
    """"Higher is better": marks of the highest ``(threshold, marks)`` pair
    with ``value >= threshold``. ``band(words, [(150, 10), (80, 7), (1, 3)])``."""
    for threshold, marks in sorted(table, key=lambda t: -t[0]):
        if value >= threshold:
            return marks
    return default


def band_max(value: float, table: list[tuple[float, float]], default: float = 0.0) -> float:
    """Like ``band`` but for "lower is better": first pair with ``value <= threshold``."""
    for threshold, marks in sorted(table, key=lambda t: t[0]):
        if value <= threshold:
            return marks
    return default


__all__.append("band_max")
