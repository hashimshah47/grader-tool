"""Text helpers: word counts, alt-text quality, spelling candidates."""
from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def word_count(text: str) -> int:
    return len(words(text))


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p for p in parts if p]


_GENERIC_ALT = {"image", "img", "picture", "photo", "pic", "icon", "logo", "graphic",
                "banner", "alt", "placeholder", "untitled", "image1", "img1", "photo1"}


def is_descriptive_alt(alt: str | None, src: str | None = None, min_words: int = 2) -> bool:
    """Heuristic: alt text that tells a text-only user what the image shows.

    Rejects missing/empty alt, filenames ("dog.jpg"), generic words ("image"),
    and very short alts (fewer than ``min_words`` words).
    """
    if alt is None:
        return False
    a = alt.strip()
    if not a:
        return False
    if re.search(r"\.(png|jpe?g|gif|bmp|webp|svg)$", a, re.I):
        return False
    if src:
        stem = re.sub(r"\.[a-z0-9]+$", "", src.split("/")[-1], flags=re.I).lower()
        if a.lower() in {stem, stem.replace("_", " "), stem.replace("-", " ")} and len(words(a)) < min_words:
            return False
    w = [x.lower() for x in words(a)]
    if not w or all(x in _GENERIC_ALT or x.isdigit() for x in w):
        return False
    return len(w) >= min_words


_spell = None

# Common words in student web pages that small dictionaries miss.
_EXTRA_WORDS = set("""
html css javascript js url urls website websites webpage webpages online offline email emails
wifi app apps internet homepage username login logout signup frontend backend github linkedin
portfolio blog vlog youtube instagram facebook tiktok podcast podcasts ok okay etc vs
""".split())


def _variants(w: str) -> list[str]:
    """Canadian/British spellings mapped to US ones (colour -> color, etc.)."""
    out = [w]
    subs = [("our", "or"), ("isation", "ization"), ("ise", "ize"), ("ised", "ized"), ("ising", "izing"),
            ("yse", "yze"), ("tre", "ter"), ("lled", "led"), ("lling", "ling"), ("ogue", "og"),
            ("ence", "ense"), ("mme", "m"), ("eable", "able")]
    for a, b in subs:
        if a in w:
            out.append(w.replace(a, b))
    return out


def spelling_candidates(text: str, ignore: set[str] | None = None) -> list[str]:
    """Words a dictionary does not recognise (lower-case, de-duplicated).

    Capitalised words (likely names/places), words with digits, file names,
    Canadian/British spellings and words in ``ignore`` are skipped.
    Returns [] if the optional ``pyspellchecker`` package is not installed.
    This is a rough signal; use ``c.ai_review`` for an actual grading decision.
    """
    global _spell
    try:
        if _spell is None:
            from spellchecker import SpellChecker  # type: ignore
            _spell = SpellChecker()
            _spell.word_frequency.load_words(_EXTRA_WORDS)
    except Exception:
        return []
    ignore = {w.lower() for w in (ignore or set())}
    # drop file names, urls and e-mail addresses before tokenising
    cleaned = re.sub(r"\S+\.(html?|css|js|png|jpe?g|gif|svg|com|ca|org)\b|\S+@\S+|https?://\S+", " ",
                     text or "", flags=re.I)
    cand = []
    for raw in words(cleaned):
        for part in re.split(r"[-’']", raw):
            if len(part) < 3 or part[0].isupper() or part.lower() in ignore:
                continue
            cand.append(part.lower())
    unknown = _spell.unknown(cand)
    seen, out = set(), []
    for w in cand:
        if w in unknown and w not in seen:
            seen.add(w)
            if all(v in unknown for v in _variants(w)) and not _spell.known(_variants(w)[1:]):
                out.append(w)
    return out
