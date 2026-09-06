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

MARKUS_REQUIRED_VERSION = "0.5.0"
_FORBIDDEN_ALLOW_HTML = re.compile(r"(?:^|\s)--allow-html(?:\s|$)")


def assert_markus_version(markus_executable: str = "markus") -> str:
    """Fail the build unless the ``markus`` CLI reports the pinned version."""
    result = subprocess.run(
        [markus_executable, "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    reported = result.stdout.strip()
    if not reported.endswith(MARKUS_REQUIRED_VERSION):
        raise RuntimeError(
            f"Markus {MARKUS_REQUIRED_VERSION} required for static builds; "
            f"got {reported!r}. Install: "
            f'pip install "git+https://github.com/AnthusAI/Markus@v{MARKUS_REQUIRED_VERSION}"'
        )
    return reported


def assert_argv_no_allow_html(argv: Sequence[str]) -> None:
    """Reject any subprocess argv that would pass ``--allow-html``."""
    joined = " ".join(argv)
    if _FORBIDDEN_ALLOW_HTML.search(joined):
        raise RuntimeError(
            "Markus build forbids --allow-html: fragments must come from "
            "repo-committed Markdown without raw HTML passthrough."
        )
