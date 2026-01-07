#!/usr/bin/env python3
import os
import runpy
import sys


def main() -> int:
    print("[DEPRECATED] Используйте: python3 tests/unit/test_free_report_generation.py", file=sys.stderr)

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    target = os.path.join(root_dir, "tests", "unit", "test_free_report_generation.py")
    runpy.run_path(target, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
