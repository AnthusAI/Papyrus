#!/usr/bin/env python3
"""Rewrite everything generated from src/papyrus_content/images/operations.py (--check lists what is out of date and changes nothing)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.images.generate import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
