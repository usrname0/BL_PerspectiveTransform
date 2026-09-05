"""
Headless test runner for BL Perspective Transform.

Usage:

    blender.exe --factory-startup --background --python tests/run.py

Exits non-zero if any suite reports a failure, so it can gate a commit or CI
step. Individual suites can be selected by name:

    blender.exe --factory-startup --background --python tests/run.py -- space
"""

import importlib
import os
import sys
import traceback

SUITES = ("test_addon", "test_space", "test_render", "test_nodes", "test_anim",
          "test_convex", "test_callbacks")


def main():
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)

    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    selected = [s for s in SUITES if not argv or any(a in s for a in argv)]

    total_failures = []
    for name in selected:
        try:
            module = importlib.import_module(name)
        except ImportError:
            print(f"[skip] {name} (not present)")
            continue

        print(f"\n=== {name} ===")
        try:
            failures = module.run()
        except Exception:
            traceback.print_exc()
            total_failures.append(f"{name}: raised during run")
            continue

        if failures:
            for failure in failures:
                print(f"  FAIL  {failure}")
            total_failures.extend(f"{name}: {f}" for f in failures)
        else:
            print("  all checks passed")

    print("\n" + "=" * 60)
    if total_failures:
        print(f"FAILED: {len(total_failures)} check(s)")
        sys.exit(1)
    print("PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
