"""Rubric text extraction and safe unpacking of student uploads."""
from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

JUNK = {"__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini", ".git", "node_modules"}
MAX_EXTRACT_BYTES = 500 * 1024 * 1024


def rubric_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(f"--- page {i + 1} ---\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages))
    if name.endswith(".docx"):
        import docx  # python-docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text.strip().replace("\n", " ") for c in row.cells))
        return "\n".join(parts)
    if name.endswith((".html", ".htm")):
        from bs4 import BeautifulSoup
        return BeautifulSoup(data.decode("utf-8", "replace"), "html.parser").get_text("\n")
    return data.decode("utf-8", "replace")


def safe_extract(zip_path: Path, dest: Path) -> None:
    """Extract a zip, refusing absolute paths, '..' and zip bombs."""
    dest = dest.resolve()
    total = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if any(part in JUNK for part in name.split("/")):
                continue
            target = (dest / name).resolve()
            if dest not in target.parents and target != dest:
                continue
            total += info.file_size
            if total > MAX_EXTRACT_BYTES:
                raise ValueError("Archive too large when extracted")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def expand_zips(root: Path, depth: int = 3) -> None:
    """Replace every .zip under root with a folder of its contents (recursively)."""
    for _ in range(depth):
        zips = [p for p in root.rglob("*.zip") if p.is_file()]
        if not zips:
            return
        for z in zips:
            target = z.with_suffix("")
            if target.exists():
                target = z.parent / (z.stem + "_zip")
            try:
                safe_extract(z, target)
            except zipfile.BadZipFile:
                pass
            z.unlink()


def _children(d: Path) -> tuple[list[Path], list[Path]]:
    dirs, files = [], []
    for c in sorted(d.iterdir()):
        if c.name in JUNK or c.name.startswith("."):
            continue
        (dirs if c.is_dir() else files).append(c)
    return dirs, files


def _is_web_file(p: Path) -> bool:
    return p.suffix.lower() in {".html", ".htm", ".css", ".js"}


def site_root(d: Path) -> Path:
    """Descend through wrapper folders until we reach the folder holding the site."""
    while True:
        dirs, files = _children(d)
        if any(_is_web_file(f) for f in files) or len(dirs) != 1:
            return d
        d = dirs[0]


def find_students(root: Path) -> list[tuple[str, Path]]:
    """Work out which folders are individual student submissions.

    Handles: a single site (HTML files at the top), a folder of student
    folders, a folder of student zips, LMS exports with one wrapper folder,
    and student folders that contain a further zip/folder.
    """
    expand_zips(root)
    node = root
    while True:
        dirs, files = _children(node)
        if len(dirs) == 1 and not any(_is_web_file(f) for f in files):
            node = dirs[0]
            continue
        break
    dirs, files = _children(node)
    if any(_is_web_file(f) for f in files):
        return [(node.name if node != root else "submission", node)]
    return [(d.name, site_root(d)) for d in dirs]


def listing(d: Path, limit: int = 60) -> str:
    out = []
    for p in sorted(d.rglob("*")):
        if p.is_file() and not any(part in JUNK for part in p.parts):
            out.append(f"{p.relative_to(d).as_posix()}  ({p.stat().st_size} bytes)")
            if len(out) >= limit:
                out.append("…")
                break
    return "\n".join(out)
