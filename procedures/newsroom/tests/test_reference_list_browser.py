"""Run ``scripts/test-reference-list-scroll-browser.ts`` (Playwright) against a synthetic site this repo's projector builds.

Skipped where ``node_modules`` (tsx and Playwright) or a Chromium is not installed, so the Python suite needs neither. Locally:
``npm run test:reference-list-browser`` does the same two steps.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from procedures.newsroom.tests.build_reference_list_site import build

ROOT = Path(__file__).resolve().parents[3]
TSX = ROOT / "node_modules" / ".bin" / "tsx"
PLAYWRIGHT = ROOT / "node_modules" / "playwright"


def chromium_available() -> bool:
    if os.environ.get("PAPYRUS_CHROMIUM_PATH"):
        return Path(os.environ["PAPYRUS_CHROMIUM_PATH"]).exists()
    return any((Path.home() / "Library" / "Caches" / "ms-playwright").glob("chromium-*")) or any((Path.home() / ".cache" / "ms-playwright").glob("chromium-*"))


@pytest.mark.skipif(not (TSX.exists() and PLAYWRIGHT.exists() and shutil.which("node") and chromium_available()), reason="node_modules (tsx, playwright) or a Chromium is not installed")
def test_paged_reference_lists_behave_in_a_real_browser(tmp_path):
    site = build(tmp_path / "site")
    result = subprocess.run(
        [str(TSX), "--test", "scripts/test-reference-list-scroll-browser.ts"],
        cwd=ROOT, env={**os.environ, "REFERENCE_LIST_SITE": str(site)}, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
