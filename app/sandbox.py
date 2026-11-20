"""Static safety checks and isolated execution for generated checker code.

Generated code is treated as untrusted:
1. ``static_check`` parses the AST and rejects disallowed imports, builtins
   and dunder access before anything runs.
2. ``run_checker`` executes it in a separate Python process with a scrubbed
   environment (no API keys), CPU/memory/file-size limits and a timeout.
Student files are only ever *read*; their JavaScript is never executed.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ALLOWED_IMPORTS = {
    "gradekit", "re", "math", "statistics", "collections", "itertools", "functools", "string",
    "json", "difflib", "textwrap", "unicodedata", "html", "typing", "dataclasses", "urllib.parse",
    "urllib", "bs4", "tinycss2", "__future__", "posixpath", "fnmatch", "enum", "operator",
}
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint", "globals", "locals",
    "vars", "getattr", "setattr", "delattr", "memoryview", "exit", "quit", "help",
}
ALLOWED_DUNDERS = {"__name__", "__init__", "__doc__", "__future__"}


def static_check(code: str) -> list[str]:
    """Return a list of problems; empty means the code may be executed."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"SyntaxError line {e.lineno}: {e.msg}"]
    problems: list[str] = []
    has_grade = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORTS and a.name.split(".")[0] not in {"gradekit", "bs4", "tinycss2"}:
                    problems.append(f"line {node.lineno}: import of '{a.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                problems.append(f"line {node.lineno}: relative imports are not allowed")
            elif mod not in ALLOWED_IMPORTS and mod.split(".")[0] not in {"gradekit", "bs4", "tinycss2"}:
                problems.append(f"line {node.lineno}: import from '{mod}' is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"line {node.lineno}: use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr not in ALLOWED_DUNDERS:
            problems.append(f"line {node.lineno}: access to '{node.attr}' is not allowed")
        elif isinstance(node, ast.Name) and node.id.startswith("__") and node.id not in ALLOWED_DUNDERS:
            problems.append(f"line {node.lineno}: use of '{node.id}' is not allowed")
        elif isinstance(node, ast.FunctionDef) and node.name == "grade" and node.col_offset == 0:
            has_grade = True
    if not has_grade:
        problems.append("The checker must define a top-level function grade(sub) -> Report")
    # de-duplicate while keeping order
    seen, out = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _limits() -> None:  # pragma: no cover - runs in the child
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (20 * 1024 * 1024, 20 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
    except Exception:
        pass
    os.setsid()


def run_checker(code: str, submission_dir: str | Path, timeout: float = 90) -> dict:
    """Run checker ``code`` against one submission folder.

    Returns ``{"ok": True, "report": {...}, "duration": s}`` or
    ``{"ok": False, "error": str, "traceback": str, "stderr": str}``.
    """
    problems = static_check(code)
    if problems:
        return {"ok": False, "error": "Static safety check failed", "problems": problems, "traceback": ""}
    with tempfile.TemporaryDirectory(prefix="chk_") as tmp:
        checker = Path(tmp) / "checker.py"
        out = Path(tmp) / "out.json"
        checker.write_text(code, encoding="utf-8")
        env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "HOME": tmp,
        }
        # -I would ignore PYTHONPATH; use -E -s plus an explicit sys.path via -c.
        bootstrap = (
            "import sys; sys.path.insert(0, %r); "
            "sys.argv = ['runner'] + sys.argv[1:]; "
            "from gradekit.runner import main; sys.exit(main())" % str(ROOT)
        )
        cmd = [sys.executable, "-E", "-s", "-c", bootstrap, str(checker), str(Path(submission_dir).resolve()), str(out)]
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd, cwd=tmp, env=env, capture_output=True, text=True, timeout=timeout,
                preexec_fn=_limits if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Checker timed out after {timeout:.0f}s", "traceback": "",
                    "duration": round(time.time() - t0, 2)}
        stderr = (proc.stderr or "")[-4000:]
        if not out.exists():
            return {"ok": False, "error": f"Checker process exited with code {proc.returncode}",
                    "traceback": stderr, "stderr": stderr, "duration": round(time.time() - t0, 2)}
        result = json.loads(out.read_text(encoding="utf-8"))
        result["stderr"] = stderr
        return result
