"""Invoke ``markus convert`` for trusted static fragments."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .security import assert_argv_no_allow_html


def convert_fragment(
    source: Path,
    *,
    theme: str | None = None,
    markus_executable: str = "markus",
) -> str:
    """Run ``markus convert --fragment --no-css`` (never ``--allow-html``)."""
    argv = [
        markus_executable,
        "convert",
        str(source),
        "--fragment",
        "--no-css",
    ]
    if theme:
        argv.extend(["--theme", theme])
    assert_argv_no_allow_html(argv)

    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"markus convert failed for {source} (exit {result.returncode}):\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout
