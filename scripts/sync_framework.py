#!/usr/bin/env python3
"""Copy the framework's .github content into junction/framework/ for packaging.

The wheel can only ship files inside the ``junction`` package, so the skills,
instructions, knowledge templates and MCP contracts that scaffold.py copies into
target repos are mirrored under ``junction/framework/github/``. Run this after
editing anything under ``.github/`` that junction distributes; the test suite
fails if the two copies drift.

Usage: python scripts/sync_framework.py [--check]
"""

from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from junction.scaffold import FRAMEWORK_DIR, FRAMEWORK_FILES  # noqa: E402


def main() -> int:
    check = "--check" in sys.argv
    drift = []
    for rel in FRAMEWORK_FILES:
        src = ROOT / rel
        dst = FRAMEWORK_DIR / rel.replace(".github/", "github/", 1)
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            continue
        drift.append(rel)
        if not check:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    if check and drift:
        print("Out of sync with .github/ (run scripts/sync_framework.py):\n  " + "\n  ".join(drift))
        return 1
    print(f"{'Checked' if check else 'Synced'} {len(FRAMEWORK_FILES)} framework files ({len(drift)} changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
