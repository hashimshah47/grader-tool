"""HTML parsing, structure queries and a lightweight, forgiving validator."""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from bs4 import BeautifulSoup, Comment, Doctype

from .text import words as _words

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}
# Elements whose end tag may legally be omitted.
OPTIONAL_END = {
    "p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot", "option",
    "optgroup", "colgroup", "rt", "rp", "html", "head", "body", "caption",
}
# Opening tag X implicitly closes an open element in IMPLICIT_CLOSE[X].
_BLOCK = {
    "address", "article", "aside", "blockquote", "div", "dl", "fieldset", "footer",
    "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol",
    "p", "pre", "section", "table", "ul", "figure", "details", "menu",
}
IMPLICIT_CLOSE = {b: {"p"} for b in _BLOCK}
IMPLICIT_CLOSE.update({
    "li": {"li", "p"}, "dt": {"dt", "dd", "p"}, "dd": {"dt", "dd", "p"},
    "tr": {"tr", "td", "th"}, "td": {"td", "th"}, "th": {"td", "th"},
    "tbody": {"thead", "tbody", "tr", "td", "th"}, "tfoot": {"thead", "tbody", "tr", "td", "th"},
    "option": {"option"}, "optgroup": {"optgroup", "option"},
    "body": {"head"},
})
KNOWN_TAGS = set("""
a abbr address area article aside audio b base bdi bdo blockquote body br button canvas
caption cite code col colgroup data datalist dd del details dfn dialog div dl dt em embed
fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe
img input ins kbd label legend li link main map mark menu meta meter nav noscript object ol
optgroup option output p param picture pre progress q rp rt ruby s samp script search section
select slot small source span strong style sub summary sup table tbody td template textarea
tfoot th thead time title tr track u ul var video wbr svg math path circle rect line polygon
polyline ellipse g defs use text tspan symbol font center big strike tt marquee frame frameset
noframes acronym applet basefont dir
""".split())
OBSOLETE_TAGS = {"font", "center", "big", "strike", "tt", "marquee", "frame", "frameset",
                 "noframes", "acronym", "applet", "basefont", "dir"}


@dataclass
class HtmlIssue:
    line: int
    message: str
    severity: str = "error"  # "error" | "warning"

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"

    def to_dict(self) -> dict:
        return {"line": self.line, "message": self.message, "severity": self.severity}


class _Validator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.issues: list[HtmlIssue] = []
        self.ids: dict[str, int] = {}
        self.start_tags: list[tuple[str, int, str]] = []  # (tag, line, raw text)
        self.end_tags: list[tuple[str, int]] = []
        self.events: list[tuple[int, int, int, str]] = []  # (line, col, 0=start/1=end, tag)

    def _issue(self, msg: str, severity: str = "error") -> None:
        self.issues.append(HtmlIssue(self.getpos()[0], msg, severity))

    def _open(self, tag: str, attrs, self_closing: bool) -> None:
        line = self.getpos()[0]
        raw = self.get_starttag_text() or ""
        self.start_tags.append((tag, line, raw))
        self.events.append((line, self.getpos()[1], 0, tag))
        if tag not in KNOWN_TAGS and "-" not in tag:
            self._issue(f"Unknown element <{tag}> (typo?)")
        elif tag in OBSOLETE_TAGS:
            self._issue(f"Obsolete element <{tag}>; use CSS instead", "warning")
        names = [a for a, _ in attrs]
        dups = {a for a in names if names.count(a) > 1}
        for a in sorted(dups):
            self._issue(f"Duplicate attribute '{a}' on <{tag}>")
        for a, v in attrs:
            if a == "id" and v:
                if v in self.ids:
                    self._issue(f"Duplicate id '{v}' (first used on line {self.ids[v]})")
                else:
                    self.ids[v] = line
        if tag == "img":
            d = dict(attrs)
            if not d.get("src"):
                self._issue("<img> is missing the src attribute")
        if raw.count('"') % 2 == 1:
            self._issue(f"Unbalanced quotes in <{tag}> tag")
        if tag in VOID or self_closing:
            return
        # implicit closes
        closes = IMPLICIT_CLOSE.get(tag, set())
        while self.stack and self.stack[-1][0] in closes:
            self.stack.pop()
        if tag == "a" and any(t == "a" for t, _ in self.stack):
            self._issue("Nested <a> elements are not allowed")
        if tag == "form" and any(t == "form" for t, _ in self.stack):
            self._issue("Nested <form> elements are not allowed")
        self.stack.append((tag, line))

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID and tag not in {"path", "circle", "rect", "line", "polygon",
                                             "polyline", "ellipse", "use", "stop"}:
            self._issue(f"<{tag} /> is not a void element; it needs a closing </{tag}>", "warning")
            self._open(tag, attrs, False)
        else:
            self._open(tag, attrs, True)

    def handle_endtag(self, tag):
        line = self.getpos()[0]
        self.end_tags.append((tag, line))
        self.events.append((line, self.getpos()[1], 1, tag))
        if tag in VOID:
            if tag == "br":
                self._issue("Stray </br>; use <br> or <br />")
            return
        if not any(t == tag for t, _ in self.stack):
            if tag not in OPTIONAL_END:
                self._issue(f"Stray end tag </{tag}> with no matching opening tag")
            return
        while self.stack:
            t, ln = self.stack.pop()
            if t == tag:
                break
            if t not in OPTIONAL_END:
                self.issues.append(HtmlIssue(ln, f"<{t}> opened on line {ln} was not closed before </{tag}>"))

    def close(self):
        super().close()
        for t, ln in self.stack:
            if t not in OPTIONAL_END:
                self.issues.append(HtmlIssue(ln, f"<{t}> opened on line {ln} is never closed"))
        self.stack = []


class HtmlDoc:
    """A parsed HTML file. ``soup`` is a BeautifulSoup tree if you need more."""

    def __init__(self, path: str, source: str) -> None:
        self.path = path
        self.source = source
        self.lines = source.splitlines()
        self.soup = BeautifulSoup(source, "html.parser")
        self._validator: _Validator | None = None

    # -- basic queries -------------------------------------------------------
    @property
    def doctype(self) -> str | None:
        for item in self.soup.contents:
            if isinstance(item, Doctype):
                return str(item).strip()
        m = re.search(r"<!DOCTYPE\s+([^>]*)>", self.source, re.I)
        return m.group(1).strip() if m else None

    @property
    def has_doctype(self) -> bool:
        return bool(re.match(r"\s*(<!--.*?-->\s*)*<!DOCTYPE\s+html", self.source, re.I | re.S))

    @property
    def title(self) -> str | None:
        t = self.soup.find("title")
        return t.get_text(strip=True) if t else None

    def find_all(self, name, **attrs):
        return self.soup.find_all(name, attrs=attrs or {})

    def count(self, name: str) -> int:
        return len(self.soup.find_all(name))

    def has(self, *names: str) -> bool:
        """True if any of the given tags is present (``has('b', 'strong')``)."""
        return any(self.soup.find(n) is not None for n in names)

    def tag_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.soup.find_all(True):
            out[t.name] = out.get(t.name, 0) + 1
        return out

    # -- text ----------------------------------------------------------------
    @property
    def text(self) -> str:
        """Visible text (no script/style/comments), whitespace-collapsed."""
        soup = BeautifulSoup(self.source, "html.parser")
        for t in soup(["script", "style", "noscript", "template"]):
            t.decompose()
        for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
            c.extract()
        body = soup.body or soup
        return re.sub(r"\s+", " ", body.get_text(" ")).strip()

    def word_count(self) -> int:
        return len(_words(self.text))

    def paragraphs(self) -> list[str]:
        return [re.sub(r"\s+", " ", p.get_text(" ")).strip() for p in self.soup.find_all("p")]

    def paragraph_word_count(self) -> int:
        return sum(len(_words(p)) for p in self.paragraphs())

    def headings(self) -> list[tuple[int, str]]:
        return [(int(h.name[1]), h.get_text(" ", strip=True))
                for h in self.soup.find_all(re.compile(r"^h[1-6]$"))]

    def comments(self) -> list[str]:
        return [str(c).strip() for c in self.soup.find_all(string=lambda s: isinstance(s, Comment))]

    # -- elements ------------------------------------------------------------
    def links(self) -> list[dict]:
        out = []
        for a in self.soup.find_all("a"):
            out.append({
                "href": a.get("href"),
                "text": a.get_text(" ", strip=True),
                "has_image": a.find("img") is not None,
                "target": a.get("target"),
            })
        return out

    def images(self) -> list[dict]:
        raw_tags = [raw for tag, _, raw in self._v().start_tags if tag == "img"]
        out = []
        for i, img in enumerate(self.soup.find_all("img")):
            raw = raw_tags[i] if i < len(raw_tags) else ""
            out.append({
                "src": img.get("src"),
                "alt": img.get("alt"),
                "width": img.get("width"),
                "height": img.get("height"),
                "usemap": img.get("usemap"),
                "title": img.get("title"),
                "self_closed": raw.rstrip().endswith("/>"),
                "in_link": img.find_parent("a") is not None,
                "style": img.get("style"),
            })
        return out

    def image_maps(self) -> list[dict]:
        used = {(i.get("usemap") or "").lstrip("#") for i in self.soup.find_all("img")}
        out = []
        for m in self.soup.find_all("map"):
            name = m.get("name") or m.get("id") or ""
            areas = [{"shape": a.get("shape"), "coords": a.get("coords"),
                      "href": a.get("href"), "alt": a.get("alt")} for a in m.find_all("area")]
            out.append({"name": name, "areas": areas, "used_by_img": name in used})
        return out

    def forms(self) -> list[dict]:
        out = []
        for f in self.soup.find_all("form"):
            fields = []
            for el in f.find_all(["input", "textarea", "select", "button"]):
                fields.append({"tag": el.name, "type": (el.get("type") or "").lower(),
                               "name": el.get("name"), "id": el.get("id")})
            out.append({"action": f.get("action"), "method": (f.get("method") or "get").lower(),
                        "fields": fields, "labels": len(f.find_all("label"))})
        return out

    def tables(self) -> list[dict]:
        out = []
        for t in self.soup.find_all("table"):
            rows = t.find_all("tr")
            out.append({
                "rows": len(rows),
                "cols": max((len(r.find_all(["td", "th"])) for r in rows), default=0),
                "has_th": t.find("th") is not None,
                "has_caption": t.find("caption") is not None,
                "id": t.get("id"), "class": t.get("class"),
                "style": t.get("style"),
                "presentational_attrs": [a for a in ("border", "bgcolor", "cellpadding",
                                                     "cellspacing", "width", "align") if t.get(a)],
            })
        return out

    def stylesheets(self) -> list[str]:
        """hrefs of <link rel="stylesheet">."""
        out = []
        for l in self.soup.find_all("link"):
            rel = l.get("rel") or []
            rel = rel if isinstance(rel, list) else [rel]
            if "stylesheet" in [r.lower() for r in rel] and l.get("href"):
                out.append(l["href"])
        return out

    def style_blocks(self) -> list[str]:
        """Contents of embedded <style> elements."""
        return [s.get_text() for s in self.soup.find_all("style")]

    def inline_styles(self) -> list[tuple[str, str]]:
        """(tag, style attribute) for every element with style="..."."""
        return [(t.name, t["style"]) for t in self.soup.find_all(style=True)]

    def scripts(self) -> list[dict]:
        return [{"src": s.get("src"), "code": s.get_text() if not s.get("src") else "",
                 "type": s.get("type"), "defer": s.has_attr("defer")}
                for s in self.soup.find_all("script")]

    def event_attributes(self) -> list[tuple[str, str, str]]:
        """Inline handlers such as onclick: (tag, attribute, code)."""
        out = []
        for t in self.soup.find_all(True):
            for a, v in t.attrs.items():
                if a.lower().startswith("on"):
                    out.append((t.name, a.lower(), v if isinstance(v, str) else " ".join(v)))
        return out

    def ids(self) -> list[str]:
        return [t["id"] for t in self.soup.find_all(id=True)]

    def classes(self) -> set[str]:
        s: set[str] = set()
        for t in self.soup.find_all(class_=True):
            s.update(t.get("class") or [])
        return s

    def meta(self) -> dict[str, str]:
        out = {}
        for m in self.soup.find_all("meta"):
            if m.get("charset"):
                out["charset"] = m["charset"]
            if m.get("name"):
                out[m["name"].lower()] = m.get("content", "")
        return out

    # -- validation ----------------------------------------------------------
    def _v(self) -> _Validator:
        if self._validator is None:
            v = _Validator()
            try:
                v.feed(self.source)
                v.close()
            except Exception as e:  # pragma: no cover - HTMLParser is very lenient
                v.issues.append(HtmlIssue(0, f"Parser failure: {e}"))
            self._validator = v
        return self._validator

    def issues(self) -> list[HtmlIssue]:
        """All validator findings (errors and warnings), plus document-level ones."""
        out = list(self._v().issues)
        if not self.has_doctype:
            out.insert(0, HtmlIssue(1, "Missing <!DOCTYPE html> at the top of the file"))
        for tag in ("html", "head", "body"):
            if not re.search(rf"<{tag}[\s>]", self.source, re.I):
                out.append(HtmlIssue(1, f"Missing <{tag}> element"))
        if not self.title:
            out.append(HtmlIssue(1, "Missing or empty <title>"))
        return out

    def errors(self) -> list[HtmlIssue]:
        """Only real syntax/structure errors (what an HTML validator would reject)."""
        return [i for i in self.issues() if i.severity == "error"]

    def warnings(self) -> list[HtmlIssue]:
        return [i for i in self.issues() if i.severity == "warning"]

    def indentation(self) -> dict:
        """Heuristic indentation quality.

        For each element whose children start on their own lines, checks that
        those child lines are indented further than the parent's line.
        Returns ``{"score": 0..1, "checked": n, "mixed_tabs_spaces": bool,
        "flush_left_ratio": 0..1, "blank_line_ratio": 0..1}``.
        """
        lines = self.source.splitlines()
        if not lines:
            return {"score": 0.0, "checked": 0, "mixed_tabs_spaces": False,
                    "flush_left_ratio": 1.0, "blank_line_ratio": 0.0}

        def indent(n: int) -> int:
            s = lines[n - 1] if 0 < n <= len(lines) else ""
            return len(s.replace("\t", "    ")) - len(s.replace("\t", "    ").lstrip())

        def starts_with_tag(n: int, tag: str) -> bool:
            s = lines[n - 1].lstrip() if 0 < n <= len(lines) else ""
            return s.lower().startswith("<" + tag)

        v = self._v()
        stack: list[tuple[str, int]] = []
        good = total = 0
        seen: set[tuple[int, int]] = set()
        # Replay start/end tags in document order with a simple open-element stack.
        for ln, _col, kind, tag in v.events:
            if kind == 0:
                if stack and starts_with_tag(ln, tag):
                    p_tag, p_ln = stack[-1]
                    if p_ln != ln and p_tag != "html" and (p_ln, ln) not in seen:
                        seen.add((p_ln, ln))
                        total += 1
                        if indent(ln) > indent(p_ln):
                            good += 1
                if tag not in VOID:
                    stack.append((tag, ln))
            else:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == tag:
                        del stack[i:]
                        break
        nonblank = [l for l in lines if l.strip()]
        leading = [l[: len(l) - len(l.lstrip())] for l in nonblank]
        mixed = any("\t" in w and " " in w for w in leading) or (
            any("\t" in w for w in leading) and any(w.startswith(" ") for w in leading))
        flush = sum(1 for w in leading if not w) / max(1, len(nonblank))
        blank = sum(1 for l in lines if not l.strip()) / max(1, len(lines))
        return {"score": round(good / total, 3) if total else (0.0 if flush > 0.9 else 1.0),
                "checked": total, "mixed_tabs_spaces": mixed,
                "flush_left_ratio": round(flush, 3), "blank_line_ratio": round(blank, 3)}
