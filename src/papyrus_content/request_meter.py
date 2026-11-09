"""Count every AppSync request a process makes, say who made it, and warn when a process spends more than its input justifies.

AppSync bills per request, so the cheapest way to find a runaway loop is to count requests where they leave the process
(`PapyrusGraphQLAuthoringClient._send_graphql`, one count per HTTP attempt). Design: docs/request-meter.md.

* A *run* is one process or one Lambda invocation. It has a caller name (`cli:references backfill-feed-keys`, `lambda:router:auto-accept`,
  `stage:<procedure>`), counts requests by caller, model and operation, and prints a one-line summary at the end: stderr for the CLI,
  a structured JSON log line for Lambdas and stages.
* A run has a *budget* that scales with its input: `base + per_unit * units`, where units are what the run declares it processed (`add_units`)
  or, for the CLI, the ids named on the command line. A fixed number for everything would be wrong in both directions.
* Going over the budget WARNS and the run continues. Stopping is a switch that is off by default: set `PAPYRUS_REQUEST_BUDGET_MODE=stop`
  (see `ENFORCE_NOT_BEFORE`). `--budget N` (CLI) or `PAPYRUS_REQUEST_BUDGET` raises one run's budget and the override is logged.
* A named sweep (`with sweep("name")`) or a run that declares itself a sweep is exempt from the budget; its requests are still counted.
* A whole-table `list_records` outside a sweep is logged as `unbounded-list` and counted, so logs and CI can find new O(N) reads.
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import json
import os
import re
import sys
import threading
from collections import Counter
from typing import Any, Callable, Iterator

ENV_MODE = "PAPYRUS_REQUEST_BUDGET_MODE"      # "warn" (default) or "stop"
ENV_BUDGET = "PAPYRUS_REQUEST_BUDGET"         # an explicit budget for this process (logged)
ENV_CALLER = "PAPYRUS_REQUEST_CALLER"         # set by a parent so a child process (a stage) is attributed to it
SUMMARY_EVENT = "papyrus_request_summary"

# Dated note (2026-11-06, Ryan's decision): the budget only warns. Stopping is meant to be switched on, with
# PAPYRUS_REQUEST_BUDGET_MODE=stop in the sites' and the router's environment, after about a week of warnings
# (not before 2026-11-13), once the first week of summaries has shown which callers need a larger budget.
ENFORCE_NOT_BEFORE = "2026-11-13"

# (base, per unit). The first week of summaries replaces these guesses; a unit is whatever the run declares (an id named on the
# command line, a delivery, a Reference examined). Longest matching prefix wins.
DEFAULT_BUDGET = (200, 8)
CONTENT_ACTIONS_PUBLISH_BASE = 60     # the publish's own reads and writes (Item, PublishedItem, media, checklist) plus the build when it runs inline
CONTENT_ACTIONS_BUILD_BASE = 10       # job bookkeeping lives in DynamoDB, not AppSync: only the summary pages and a few records
CONTENT_ACTIONS_PER_BUILD = 12        # one Story built: its Item and PublishedItem, its lineage, two summary passes, a media list, a few ratings
BUDGETS: dict[str, tuple[int, int]] = {
    "lambda:router:route": (400, 8),
    "lambda:router:collect": (300, 8),
    "lambda:router:feedback": (300, 2),
    "lambda:router:auto-accept": (300, 1),     # batched: about one request per 25 References examined, plus the index pages
    "lambda:router:monitor-stories": (600, 20),
    "lambda:router": (300, 8),
    "lambda:monitor-collector": (300, 8),
    "lambda:procedure-runner": (300, 8),
    "stage:": (300, 8),
    "cli:": DEFAULT_BUDGET,
    # The content-actions function, one run per invocation (PPY-3acc8d). A publish and the build of its pages read a fixed number of records
    # whatever the size of the site (the bodies other pages need come from the body cache, not one read per Story); a unit is one Story built.
    # features_backend/publish-cost.feature and procedures/newsroom/tests/test_publish_cost.py hold them to these numbers.
    "lambda:content-actions:publishItem": (CONTENT_ACTIONS_PUBLISH_BASE, 0),
    "lambda:content-actions:saveItemDraft": (CONTENT_ACTIONS_PUBLISH_BASE, 0),
    "lambda:content-actions:item": (CONTENT_ACTIONS_BUILD_BASE, CONTENT_ACTIONS_PER_BUILD),
    "lambda:content-actions:item-pages": (CONTENT_ACTIONS_BUILD_BASE, CONTENT_ACTIONS_PER_BUILD),
    "lambda:content-actions:drain": (CONTENT_ACTIONS_BUILD_BASE, CONTENT_ACTIONS_PER_BUILD),
    "lambda:content-actions": DEFAULT_BUDGET,
}

# CLI commands that read or write a whole corpus on purpose. They declare themselves sweeps: counted, never budget-checked.
SWEEP_COMMAND = re.compile(
    r"backfill|sweep|adopt-tenant|copy-backend|rebuild|recount|repair|migrate|sync-|import|export|snapshot|dedupe|reindex|audit|rehydrat|"
    r"publish-graph|training|priming|copywriting-output|run-copywriting|worker-bootstrap")
SWEEP_GROUPS = frozenset({"knowledge", "wiki"})


class RequestBudgetExceeded(Exception):
    """Raised only when stop mode is on (`PAPYRUS_REQUEST_BUDGET_MODE=stop`). Not a RuntimeError: the client retries those."""


_OPERATION = re.compile(r"^\s*(?:query|mutation)\s+(\w+)", re.MULTILINE)
_OPERATION_PREFIX = re.compile(r"^(?:Batch(?:Get|Index))?(?:List|Get|Create|Update|Delete)?")


def operation_name(query: str) -> str:
    match = _OPERATION.search(query or "")
    return match.group(1) if match else "anonymous"


def model_of_operation(operation: str) -> str:
    """The model an operation name is about, when the caller did not say: `ListReferencesByFeedState...` is `References`."""
    stripped = _OPERATION_PREFIX.sub("", operation, count=1)
    return re.split(r"By[A-Z]", stripped, maxsplit=1)[0] or operation


def budget_parameters(caller: str) -> tuple[int, int]:
    best = max((prefix for prefix in BUDGETS if caller.startswith(prefix)), key=len, default=None)
    return BUDGETS[best] if best else DEFAULT_BUDGET


def is_sweep_command(group: str, command: str) -> bool:
    return group in SWEEP_GROUPS or bool(SWEEP_COMMAND.search(command))


class Run:
    def __init__(self, caller: str, *, units: int = 0, sweep: bool = False, emit: str = "log", budget: int | None = None) -> None:
        self.caller = caller
        self.units = units
        self.sweep = sweep
        self.emit = emit                     # "stderr" (one line of text) or "log" (one JSON line on stdout)
        self.lock = threading.Lock()
        self.requests = 0                    # every request, sweeps included
        self.budgeted = 0                    # requests outside named sweeps; this is what the budget limits
        self.aliases = 0                     # reads folded into aliased requests (they cost one request each batch)
        self.by_key: Counter[tuple[str, str, str]] = Counter()   # (sweep name or "", model, operation)
        self.unbounded: Counter[str] = Counter()                 # model -> whole-table lists outside a sweep
        self.warned = False
        self.finished = False
        base, per_unit = budget_parameters(caller)
        self.base, self.per_unit = base, per_unit
        self.override = budget
        env_budget = os.environ.get(ENV_BUDGET)
        if self.override is None and env_budget and env_budget.isdigit():
            self.override = int(env_budget)
        if self.override is not None:
            default = self.budget(use_override=False)
            _log(self.emit, {"event": "papyrus_request_budget_override", "caller": caller, "budget": self.override, "default": default},
                 text=f"papyrus request meter: {caller} runs with a budget of {self.override} (override; the default would be {default})")

    def budget(self, *, use_override: bool = True) -> int:
        if use_override and self.override is not None:
            return self.override
        return self.base + self.per_unit * self.units

    def add_units(self, count: int) -> None:
        with self.lock:
            self.units += max(0, int(count))

    def record(self, query: str, model: str | None, sweep_name: str | None, aliases: int = 0) -> None:
        operation = operation_name(query)
        exceeded: str | None = None
        with self.lock:
            self.requests += 1
            self.aliases += aliases
            self.by_key[(sweep_name or "", model or model_of_operation(operation), operation)] += 1
            if not (sweep_name or self.sweep):
                self.budgeted += 1
                if self.budgeted > self.budget() and not self.warned:
                    self.warned = True
                    exceeded = self.over_budget_message()
        if exceeded:
            _log(self.emit, {"event": "papyrus_request_over_budget", "message": exceeded, **self.summary_fields()}, text=exceeded)
            if os.environ.get(ENV_MODE, "warn").lower() == "stop":
                raise RequestBudgetExceeded(exceeded)

    def over_budget_message(self) -> str:
        return (f"WARNING papyrus request meter: {self.caller} has made {self.budgeted} AppSync requests outside named sweeps, over its budget of "
                f"{self.budget()} ({self.base} + {self.per_unit} x {self.units} units"
                f"{', overridden' if self.override is not None else ''}). It continues; "
                f"see docs/request-meter.md. Top: {self.top_text()}")

    def top_text(self, count: int = 3) -> str:
        totals: Counter[str] = Counter()
        for (sweep_name, model, operation), n in self.by_key.items():
            totals[f"{model}.{operation}" + (f"[sweep {sweep_name}]" if sweep_name else "")] += n
        return ", ".join(f"{name} x{n}" for name, n in totals.most_common(count)) or "none"

    def note_unbounded(self, model: str) -> bool:
        with self.lock:
            first = self.unbounded[model] == 0
            self.unbounded[model] += 1
            return first

    def summary_fields(self) -> dict[str, Any]:
        with self.lock:
            totals: Counter[str] = Counter()
            for (sweep_name, model, operation), n in self.by_key.items():
                totals[f"{model}.{operation}"] += n
            return {"caller": self.caller, "requests": self.requests, "budgeted": self.budgeted, "budget": None if self.sweep else self.budget(),
                    "units": self.units, "sweep": self.sweep, "aliasedReads": self.aliases,
                    "unboundedLists": dict(self.unbounded), "top": dict(totals.most_common(8))}

    def summary_line(self) -> str:
        fields = self.summary_fields()
        budget = "exempt (named sweep)" if self.sweep else f"{fields['budgeted']}/{fields['budget']}"
        unbounded = f" unbounded-lists={sum(self.unbounded.values())}" if self.unbounded else ""
        return (f"papyrus requests: {self.caller} total={fields['requests']} budget={budget} units={self.units}{unbounded} "
                f"top: {self.top_text()}")

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        if self.requests == 0:
            return
        _log(self.emit, {"event": SUMMARY_EVENT, **self.summary_fields()}, text=self.summary_line())


def _log(emit: str, payload: dict[str, Any], *, text: str | None = None) -> None:
    try:
        if emit == "stderr":
            print(text or json.dumps(payload, default=str), file=sys.stderr, flush=True)
        else:
            print(json.dumps(payload, default=str), flush=True)
    except Exception:   # a meter must never break the work it measures
        pass


_current: Run | None = None
_current_lock = threading.Lock()
_sweep: contextvars.ContextVar[str | None] = contextvars.ContextVar("papyrus_request_sweep", default=None)
_model: contextvars.ContextVar[str | None] = contextvars.ContextVar("papyrus_request_model", default=None)
_atexit_registered = False


def current_run() -> Run:
    """The active run; a process that never started one gets an implicit run, summarised at exit."""
    global _current, _atexit_registered
    with _current_lock:
        if _current is None:
            _current = Run(os.environ.get(ENV_CALLER) or f"process:{os.path.basename(sys.argv[0] or 'python')}", emit="stderr" if sys.stderr.isatty() else "log")
            if not _atexit_registered:
                atexit.register(finish_current)
                _atexit_registered = True
        return _current


def finish_current() -> None:
    global _current
    with _current_lock:
        run, _current = _current, None
    if run is not None:
        run.finish()


@contextlib.contextmanager
def run(caller: str, *, units: int = 0, sweep: bool = False, emit: str = "log", budget: int | None = None) -> Iterator[Run]:
    """One metered run (a CLI command, a Lambda invocation). Nested runs share the outer run and only add units."""
    global _current
    with _current_lock:
        outer = _current
    if outer is not None and not outer.finished and outer.caller != caller and outer.requests == 0 and outer.caller.startswith("process:"):
        finish_current()   # an implicit run that counted nothing yet: replace it
        outer = None
    if outer is not None and not outer.finished:
        outer.add_units(units)
        yield outer
        return
    started = Run(caller, units=units, sweep=sweep, emit=emit, budget=budget)
    with _current_lock:
        _current = started
    try:
        yield started
    finally:
        with _current_lock:
            if _current is started:
                _current = None
        started.finish()


@contextlib.contextmanager
def sweep(name: str) -> Iterator[None]:
    """A named whole-table read or backfill. Requests inside are counted under the sweep's name and are not checked against the budget."""
    token = _sweep.set(name)
    try:
        yield
    finally:
        _sweep.reset(token)


@contextlib.contextmanager
def model(name: str) -> Iterator[None]:
    token = _model.set(name)
    try:
        yield
    finally:
        _model.reset(token)


def add_units(count: int) -> None:
    current_run().add_units(count)


def record_request(query: str, *, aliases: int = 0) -> None:
    """Called once per HTTP attempt to AppSync."""
    current_run().record(query, _model.get(), _sweep.get(), aliases)


def note_unbounded_list(model_name: str) -> None:
    """A `list_records` with no key condition. Outside a named sweep it is logged (once per model per run) and counted."""
    if _sweep.get():
        return
    active = current_run()
    if active.note_unbounded(model_name) and not active.sweep:
        _log(active.emit, {"event": "papyrus_unbounded_list", "caller": active.caller, "model": model_name},
             text=f"WARNING papyrus request meter: unbounded list of every {model_name} row by {active.caller}, outside a named sweep. "
                  f"Read through an index, or wrap it in request_meter.sweep(\"<name>\") and add it to the allowlist.")


def reset_for_tests() -> None:
    global _current
    with _current_lock:
        _current = None


def cli_units(arguments: list[str]) -> int:
    """Ids named on the command line: every token that is not a flag. (A flag's value counts too, which only makes the budget a little generous.)"""
    return sum(1 for token in arguments if token and not token.startswith("-"))


def split_budget_flag(arguments: list[str]) -> tuple[list[str], int | None]:
    """Remove `--budget N` / `--budget=N` from the arguments; the other commands never see it."""
    kept: list[str] = []
    budget: int | None = None
    skip = False
    for index, token in enumerate(arguments):
        if skip:
            skip = False
            continue
        if token == "--budget" and index + 1 < len(arguments) and arguments[index + 1].isdigit():
            budget, skip = int(arguments[index + 1]), True
        elif token.startswith("--budget=") and token.split("=", 1)[1].isdigit():
            budget = int(token.split("=", 1)[1])
        else:
            kept.append(token)
    return kept, budget


def lambda_caller(name: str, event: Any = None, *, key: str = "task") -> str:
    task = event.get(key) if isinstance(event, dict) else None
    return f"lambda:{name}" + (f":{task}" if task else "")


def metered_handler(name: str, task_key: str = "task") -> Callable:
    """Decorator for a Lambda entry point: one run per invocation, summary as a JSON log line."""
    def decorate(function: Callable) -> Callable:
        def wrapper(event, context=None):
            with run(lambda_caller(name, event, key=task_key), emit="log"):
                return function(event, context)
        wrapper.__name__, wrapper.__doc__, wrapper.__wrapped__ = function.__name__, function.__doc__, function
        return wrapper
    return decorate
