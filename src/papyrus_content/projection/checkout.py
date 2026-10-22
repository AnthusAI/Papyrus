"""Warn when the site checkout given as ``--static-dir`` is behind its upstream branch."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

GIT_TIMEOUT_SECONDS = 30


def _git(directory: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(directory), *arguments], capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, check=False
    )


def commits_behind_upstream(directory: Path) -> tuple[int, str] | None:
    """How many commits the checkout lacks, and the upstream's name; ``None`` when it has no upstream to compare with."""
    inside = _git(directory, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    name = _git(directory, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if name.returncode != 0:
        return None
    fetched = _git(directory, "fetch", "--quiet")
    if fetched.returncode != 0:
        raise RuntimeError(fetched.stderr.strip() or "git fetch failed")
    count = _git(directory, "rev-list", "--count", "HEAD..@{u}")
    if count.returncode != 0:
        raise RuntimeError(count.stderr.strip() or "git rev-list failed")
    return int(count.stdout.strip()), name.stdout.strip()


def warn_if_checkout_is_behind(static_directory: str) -> None:
    """Print a warning to stderr when the checkout is behind; never refuses and never raises."""
    directory = Path(static_directory).expanduser()
    try:
        behind = commits_behind_upstream(directory)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"warning: could not check whether --static-dir {static_directory} is current: {error}", file=sys.stderr)
        return
    if behind is None or behind[0] <= 0:
        return
    count, upstream = behind
    noun = "commit" if count == 1 else "commits"
    print(
        f"warning: --static-dir {static_directory} is {count} {noun} behind {upstream}; "
        "projection.json and templates come from this checkout. Update it or use a fresh worktree of origin/main.",
        file=sys.stderr,
    )
