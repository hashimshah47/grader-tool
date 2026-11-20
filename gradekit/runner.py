"""Entry point executed inside the sandbox subprocess.

    python -I -m gradekit.runner  <checker.py> <submission_dir> <out.json>

Loads the checker, calls ``grade(Submission(dir))`` and writes the report
JSON (or the error) to ``out.json``. Anything the checker prints goes to
stderr so it cannot corrupt the result.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
import time
import traceback


def main() -> int:
    checker_path, submission_dir, out_path = sys.argv[1:4]
    t0 = time.time()
    result: dict
    try:
        from gradekit import Report, Submission

        spec = importlib.util.spec_from_file_location("checker", checker_path)
        mod = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(sys.stderr):
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            if not hasattr(mod, "grade"):
                raise RuntimeError("Checker must define grade(sub) -> Report")
            report = mod.grade(Submission(submission_dir))
        if not isinstance(report, Report):
            raise TypeError(f"grade() must return a gradekit.Report, got {type(report).__name__}")
        result = {"ok": True, "report": report.to_dict()}
    except BaseException as e:  # noqa: BLE001 - report everything back
        result = {"ok": False, "error": f"{type(e).__name__}: {e}",
                  "traceback": traceback.format_exc()[-4000:]}
    result["duration"] = round(time.time() - t0, 3)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
