"""Invoke ``markus convert`` for trusted static fragments."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .security import assert_argv_no_allow_html, assert_supported_markus_version

if TYPE_CHECKING:
    from .transforms import FragmentTransform


def convert_fragment(
    source: Path,
    *,
    theme: str | None = None,
    markus_executable: str = "markus",
    transform: FragmentTransform | None = None,
) -> str:
    """Run ``markus convert --fragment --no-css`` (never ``--allow-html``).

    ``transform``, when given, is applied to the converted fragment (see
    ``transforms.py``). ``None`` returns Markus's output untouched.
    """
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
    if transform is None:
        return result.stdout
    return transform.apply(result.stdout)


def convert_text_in_process(text: str, *, theme: str | None = None) -> str:
    """Convert Markus source to a fragment in this process, matching the CLI's bytes.

    Same contract as :func:`convert_fragment` (fragment, no CSS, raw HTML never
    allowed) without the subprocess, and the CLI's trailing newline.
    """
    import markusmd

    assert_supported_markus_version(markusmd.__version__)
    fragment = markusmd.convert(
        text, allow_html=False, include_css=False, full_document=False, theme=theme
    )
    return fragment if fragment.endswith("\n") else fragment + "\n"
