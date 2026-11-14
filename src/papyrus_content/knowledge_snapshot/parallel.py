"""Run many independent backend requests at once, one client (one connection) per worker thread.

The authoring client keeps one HTTPS connection, so it is not shared between threads: every worker makes its own from the factory.
Results come back in input order; the first failure is raised after the workers stop. ``workers`` of 1 (or no factory) is the plain loop
over the one client, so a test or a small run behaves exactly as before.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

Item = TypeVar("Item")
Result = TypeVar("Result")

DEFAULT_WORKERS = 8
MAXIMUM_WORKERS = 32


def worker_count(value: Any, default: int = DEFAULT_WORKERS) -> int:
    """A whole number of workers from 1 to ``MAXIMUM_WORKERS``; the default when ``value`` is not given."""
    if value in (None, True, ""):
        return default
    try:
        count = int(str(value))
    except ValueError as error:
        raise ValueError(f"--parallel must be a whole number from 1 to {MAXIMUM_WORKERS}, not {value!r}.") from error
    if not 1 <= count <= MAXIMUM_WORKERS:
        raise ValueError(f"--parallel must be a whole number from 1 to {MAXIMUM_WORKERS}, not {count}.")
    return count


def map_with_clients(
    items: Iterable[Item], work: Callable[[Any, Item], Result], *, client: Any, client_factory: Callable[[], Any] | None, workers: int
) -> list[Result]:
    """``[work(client, item) for item in items]``, with up to ``workers`` threads, each using a client of its own."""
    entries: Sequence[Item] = list(items)
    if workers <= 1 or client_factory is None or len(entries) <= 1:
        return [work(client, entry) for entry in entries]
    local = threading.local()

    def run(entry: Item) -> Result:
        if not hasattr(local, "client"):
            local.client = client_factory()
        return work(local.client, entry)

    with ThreadPoolExecutor(max_workers=min(workers, len(entries))) as executor:
        return list(executor.map(run, entries))
