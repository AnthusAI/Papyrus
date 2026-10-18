"""Build-time security invariants for Markus static output.

`markus validate` checks directive vocabulary only — it is NOT a security
control and must not be treated as XSS protection. The real invariant is:
fragments are built in CI from repo-committed Markdown with ``--allow-html``
OFF. These helpers enforce that at build time.
"""

from __future__ import annotations

import re
import subprocess
from typing import Sequence

# Same range as the ``anthus-markus`` dependency in pyproject.toml. A Markus
# outside it, or one whose version cannot be read, fails the build.
MARKUS_MIN_VERSION = (0, 5, 1)
MARKUS_MAX_VERSION_EXCLUSIVE = (1, 0, 0)
MARKUS_SUPPORTED_RANGE = ">=0.5.1,<1.0.0"
_FORBIDDEN_ALLOW_HTML = re.compile(r"(?:^|\s)--allow-html(?:\s|$)")
_RELEASE_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def assert_supported_markus_version(version: str, *, purpose: str = "static builds") -> str:
    """Return ``version`` if it is a plain release inside the supported range, else raise."""
    match = _RELEASE_VERSION.fullmatch(version.strip())
    parsed = tuple(int(part) for part in match.groups()) if match else None
    if parsed is None or not MARKUS_MIN_VERSION <= parsed < MARKUS_MAX_VERSION_EXCLUSIVE:
        raise RuntimeError(
            f"Markus {MARKUS_SUPPORTED_RANGE} required for {purpose}; got {version!r}. "
            f'Install: pip install "anthus-markus{MARKUS_SUPPORTED_RANGE}"'
        )
    return version.strip()


def assert_markus_version(markus_executable: str = "markus") -> str:
    """Fail the build unless the ``markus`` CLI reports a supported version."""
    result = subprocess.run(
        [markus_executable, "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    reported = result.stdout.strip()
    words = reported.split()
    if len(words) != 2 or words[0] != "markus":
        raise RuntimeError(
            f"Markus {MARKUS_SUPPORTED_RANGE} required for static builds; "
            f"could not read a version from {reported!r}."
        )
    return assert_supported_markus_version(words[1])


def assert_argv_no_allow_html(argv: Sequence[str]) -> None:
    """Reject any subprocess argv that would pass ``--allow-html``."""
    joined = " ".join(argv)
    if _FORBIDDEN_ALLOW_HTML.search(joined):
        raise RuntimeError(
            "Markus build forbids --allow-html: fragments must come from "
            "repo-committed Markdown without raw HTML passthrough."
        )
