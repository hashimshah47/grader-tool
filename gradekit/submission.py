"""Access to one student's submitted files (read-only)."""
from __future__ import annotations

import fnmatch
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from .css import CssDoc
from .html import HtmlDoc
from .js import JsDoc

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}
HTML_EXT = {".html", ".htm"}


@dataclass
class FileMatch:
    """Result of looking for a required file by name."""
    expected: str
    path: str | None          # actual relative path found (None = missing)
    exact: bool               # True if the name matches exactly (case-sensitive)

    @property
    def found(self) -> bool:
        return self.path is not None

    @property
    def problem(self) -> str | None:
        if self.path is None:
            return f"Missing required file '{self.expected}'"
        if not self.exact:
            return f"File should be named '{self.expected}' but is '{self.path}'"
        return None


@dataclass
class LinkCheck:
    href: str
    kind: str                 # internal | external | anchor | mailto | tel | javascript | empty
    ok: bool                  # internal target exists (exact case) / non-internal always True
    target: str | None = None  # resolved relative path for internal links
    case_mismatch: bool = False  # exists only with different letter case (breaks on Linux servers)

    @property
    def problem(self) -> str | None:
        if self.kind == "empty":
            return "Link has an empty href"
        if self.kind != "internal" or self.ok:
            return None
        if self.case_mismatch:
            return f"'{self.href}' only matches a file with different capitalisation (breaks on the web server)"
        return f"Broken link: '{self.href}' does not exist"


class Submission:
    """A student's submission folder.

    All paths are POSIX-style and relative to the submission root.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._files: list[str] = sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and "__MACOSX" not in p.parts and not p.name.startswith(".")
        )
        self._cache: dict = {}

    @property
    def name(self) -> str:
        return self.root.name

    # -- listing -------------------------------------------------------------
    def files(self, pattern: str = "*") -> list[str]:
        """Relative paths whose *basename* matches a glob (case-insensitive)."""
        pat = pattern.lower()
        return [f for f in self._files if fnmatch.fnmatch(posixpath.basename(f).lower(), pat)
                or fnmatch.fnmatch(f.lower(), pat)]

    def html_files(self) -> list[str]:
        return [f for f in self._files if Path(f).suffix.lower() in HTML_EXT]

    def css_files(self) -> list[str]:
        return [f for f in self._files if f.lower().endswith(".css")]

    def js_files(self) -> list[str]:
        return [f for f in self._files if f.lower().endswith(".js")]

    def image_files(self) -> list[str]:
        return [f for f in self._files if Path(f).suffix.lower() in IMAGE_EXT]

    def exists(self, relpath: str) -> bool:
        """Exact, case-sensitive existence check."""
        return relpath in self._files

    # -- finding required files --------------------------------------------
    def find(self, filename: str, case_sensitive: bool = False) -> str | None:
        """Find a file by name anywhere in the submission (shallowest first)."""
        if filename in self._files:
            return filename
        target = filename.lower() if not case_sensitive else filename
        cands = []
        for f in self._files:
            base = posixpath.basename(f)
            cmp = base if case_sensitive else base.lower()
            full = f if case_sensitive else f.lower()
            if cmp == posixpath.basename(target) or full == target:
                cands.append(f)
        cands.sort(key=lambda f: (f.count("/"), f))
        return cands[0] if cands else None

    def expect_file(self, filename: str, alternatives: list[str] | None = None) -> FileMatch:
        """Look for a required file and report whether its name is exactly right.

        ``alternatives`` are near-miss names to accept as "found but misnamed",
        e.g. ``expect_file("mybio.html", ["mybio.htm", "my_bio.html"])``.
        """
        exact = self.find(filename, case_sensitive=True)
        if exact:
            return FileMatch(filename, exact, posixpath.basename(exact) == posixpath.basename(filename))
        loose = self.find(filename)
        if loose:
            return FileMatch(filename, loose, False)
        stem = Path(filename).stem.lower()
        for alt in (alternatives or []):
            f = self.find(alt)
            if f:
                return FileMatch(filename, f, False)
        # same stem, other html extension (.htm vs .html)
        for f in self._files:
            if Path(f).stem.lower() == stem and Path(f).suffix.lower() in (HTML_EXT if Path(filename).suffix.lower() in HTML_EXT else {Path(filename).suffix.lower()}):
                return FileMatch(filename, f, False)
        return FileMatch(filename, None, False)

    # -- reading -------------------------------------------------------------
    def path(self, relpath: str) -> Path:
        p = (self.root / relpath).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("path escapes submission")
        return p

    def read_bytes(self, relpath: str) -> bytes:
        return self.path(relpath).read_bytes()

    def read_text(self, relpath: str) -> str:
        data = self.read_bytes(relpath)
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", "replace")

    def size(self, relpath: str) -> int:
        return self.path(relpath).stat().st_size

    def _resolve_name(self, name: str) -> str | None:
        return name if name in self._files else self.find(name)

    def html(self, name: str) -> HtmlDoc | None:
        """Parsed HTML for a file (found case-insensitively); None if missing."""
        rel = self._resolve_name(name)
        if rel is None:
            return None
        key = ("html", rel)
        if key not in self._cache:
            self._cache[key] = HtmlDoc(rel, self.read_text(rel))
        return self._cache[key]

    def css(self, name: str) -> CssDoc | None:
        rel = self._resolve_name(name)
        if rel is None:
            return None
        key = ("css", rel)
        if key not in self._cache:
            self._cache[key] = CssDoc(rel, self.read_text(rel))
        return self._cache[key]

    def js(self, name: str) -> JsDoc | None:
        rel = self._resolve_name(name)
        if rel is None:
            return None
        key = ("js", rel)
        if key not in self._cache:
            self._cache[key] = JsDoc(rel, self.read_text(rel))
        return self._cache[key]

    def all_html(self) -> list[HtmlDoc]:
        return [self.html(f) for f in self.html_files()]

    # -- images ----------------------------------------------------------------
    def image_info(self, relpath: str) -> dict | None:
        """{'bytes', 'width', 'height', 'format'} for an image file; None if missing."""
        rel = relpath if relpath in self._files else None
        if rel is None:
            return None
        info = {"path": rel, "bytes": self.size(rel), "width": None, "height": None, "format": None}
        if rel.lower().endswith(".svg"):
            info["format"] = "SVG"
            return info
        try:
            from PIL import Image  # type: ignore
            with Image.open(self.path(rel)) as im:
                info.update(width=im.width, height=im.height, format=im.format)
        except Exception:
            pass
        return info

    # -- links -----------------------------------------------------------------
    def resolve(self, from_file: str, href: str | None) -> LinkCheck:
        """Resolve a link/src found in ``from_file`` against the submission."""
        if href is None or not href.strip():
            return LinkCheck(href or "", "empty", False)
        href = href.strip()
        low = href.lower()
        if low.startswith("#"):
            return LinkCheck(href, "anchor", True)
        if low.startswith("mailto:"):
            return LinkCheck(href, "mailto", True)
        if low.startswith("tel:"):
            return LinkCheck(href, "tel", True)
        if low.startswith("javascript:"):
            return LinkCheck(href, "javascript", True)
        u = urlparse(href)
        if u.scheme in ("http", "https", "ftp") or href.startswith("//"):
            return LinkCheck(href, "external", True)
        if u.scheme == "file" or re.match(r"^[a-zA-Z]:[\\/]", href) or href.startswith("\\"):
            return LinkCheck(href, "internal", False, None)  # local disk path: broken online
        path = unquote(u.path).replace("\\", "/")
        if not path:
            return LinkCheck(href, "anchor", True)
        base = posixpath.dirname(from_file)
        target = posixpath.normpath(posixpath.join(base, path.lstrip("/") if path.startswith("/") else path))
        if path.startswith("/"):
            target = posixpath.normpath(path.lstrip("/"))
        if target.endswith("/") or target == ".":
            target = posixpath.join(target, "index.html")
        if target in self._files:
            return LinkCheck(href, "internal", True, target)
        ci = [f for f in self._files if f.lower() == target.lower()]
        if ci:
            return LinkCheck(href, "internal", False, ci[0], case_mismatch=True)
        return LinkCheck(href, "internal", False, target)

    def link_report(self, html_name: str) -> list[LinkCheck]:
        """Check every <a href> in an HTML file."""
        doc = self.html(html_name)
        if doc is None:
            return []
        return [self.resolve(doc.path, l["href"]) for l in doc.links()]

    def links_to(self, html_name: str, target_name: str) -> bool:
        """True if ``html_name`` has a working link to ``target_name``."""
        tgt = self._resolve_name(target_name)
        return any(lc.ok and lc.target == tgt for lc in self.link_report(html_name)) if tgt else False
