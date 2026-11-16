"""``papyrus pod init|id|check``: work on a folder of notes. No sign-in, no site, no network; ``check`` only reads.

Exit status: 0 for success, 1 when ``check`` found problems, 2 for a command that could not run (the operator-error status).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import TextIO
import sys

from papyrus_content.operator_errors import OperatorError

from . import context, profile
from .check import POD_LEVEL, REVIEW_CLAIMS_LINE, check_pod

ROUTES = {"init": {}, "id": {}, "check": {}}
USAGE = {
    "init": "papyrus pod init POD --id-base URL",
    "id": "papyrus pod id POD [N]",
    "check": "papyrus pod check POD",
}


def route_tree() -> dict:
    return {name: dict(node) for name, node in ROUTES.items()}


def command(argv: list[str], *, stdout: TextIO | None = None) -> int:
    out = stdout or sys.stdout
    if not argv or argv[0] not in ROUTES:
        raise ValueError("papyrus pod requires <command>: init, id or check.")
    name, rest = argv[0], argv[1:]
    return {"init": _init, "id": _id, "check": _check}[name](rest, out)


def _pod_argument(args: list[str], name: str) -> Path:
    if not args or args[0].startswith("-"):
        raise ValueError(f"papyrus pod {name} requires POD, the folder of notes.")
    return Path(args[0])


def _existing(pod: Path) -> Path:
    if not pod.is_dir():
        raise OperatorError(f"{pod} is not a folder. Nothing was read.")
    return pod


def _init(args: list[str], out: TextIO) -> int:
    pod = _pod_argument(args, "init")
    rest = args[1:]
    base = ""
    if rest[:1] == ["--id-base"]:
        base = rest[1] if len(rest) > 1 else ""
        rest = rest[2:]
    elif rest and rest[0].startswith("--id-base="):
        base, rest = rest[0].partition("=")[2], rest[1:]
    if rest:
        raise ValueError(f"papyrus pod init does not take {rest[0]!r}; the usage is {USAGE['init']}.")
    if not base:
        raise ValueError("papyrus pod init requires --id-base URL, the address every note id starts with, such as https://example.org/id/.")
    problem = context.id_base_problem(base)
    if problem:
        raise OperatorError(f"--id-base: {problem}. Nothing was written.")
    root = pod / profile.CONTEXT_FILE
    if root.exists():
        raise OperatorError(f"{pod} is already a level 1 pod ({profile.CONTEXT_FILE} exists). Edit that file by hand to change the id base or declare site keys. Nothing was written.")
    if pod.exists() and not pod.is_dir():
        raise OperatorError(f"{pod} is not a folder. Nothing was written.")
    pod.mkdir(parents=True, exist_ok=True)
    (pod / profile.PROFILE_CONTEXT_FILE).write_text(context.generate(), encoding="utf-8")
    root.write_text(context.root_context(base), encoding="utf-8")
    print(f"{pod}: level 1 pod started with {profile.CONTEXT_FILE} and {profile.PROFILE_CONTEXT_FILE} (profile version {profile.PROFILE_VERSION}, id base {base}). "
          "No note was changed.", file=out)
    return 0


def _id(args: list[str], out: TextIO) -> int:
    pod = _pod_argument(args, "id")
    rest = args[1:]
    if len(rest) > 1:
        raise ValueError(f"papyrus pod id does not take {rest[1]!r}; the usage is {USAGE['id']}.")
    count = 1
    if rest:
        if not rest[0].isdecimal() or int(rest[0]) < 1:
            raise ValueError(f"papyrus pod id takes a whole number of ids, one or more; got {rest[0]!r}.")
        count = int(rest[0])
    root = _existing(pod) / profile.CONTEXT_FILE
    if not root.is_file():
        raise OperatorError(f"{pod} has no {profile.CONTEXT_FILE}; run `papyrus pod init {pod} --id-base URL` first. No id was made.")
    declared, problems = context.read_root(root)
    if not declared.id_base:
        raise OperatorError(f"{root} does not name a usable id base ({'; '.join(problems)}). No id was made.")
    for _ in range(count):
        print(f"{declared.id_base}{uuid.uuid4()}", file=out)
    return 0


def _check(args: list[str], out: TextIO) -> int:
    pod = _pod_argument(args, "check")
    if len(args) > 1:
        raise ValueError(f"papyrus pod check does not take {args[1]!r}; the usage is {USAGE['check']}.")
    report = check_pod(_existing(pod))
    print(f"pod: {report.pod}", file=out)
    if report.level == 0:
        detail = "no notes yet" if not report.notes else f"{report.notes} notes, none typed"
        print(f"level: 0 ({detail})", file=out)
    else:
        print(f"level: 1 ({report.typed} of {report.notes} notes typed)", file=out)
        print(f"history: {report.history}", file=out)
        print(f"review: {REVIEW_CLAIMS_LINE}", file=out)
    if not report.problems:
        print("ok: no problems", file=out)
        return 0
    print(f"problems: {len(report.problems)}", file=out)
    for problem in report.problems:
        where = "" if problem.path == POD_LEVEL else f"{problem.path}: "
        print(f"  {where}{problem.message}", file=out)
    return 1
