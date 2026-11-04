"""The Lambda's side of the stream trigger: the private state and the list of changed rows, found in the lock table the task already uses."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from typing import Any

from ..projection.lease import lock_table_from_environment
from .state_store import DirtyBatch, DirtyStore, DynamoStateStore

INCREMENTAL_FIELD = "incremental"
SCOPE_FIELD = "scope"
SCOPE_CHARACTERS = 8
FUNCTION_NAME_ENVIRONMENT = "AWS_LAMBDA_FUNCTION_NAME"


def scope_of(function_name: str) -> str:
    """The short stable name of a site's backend. The trigger computes the same from the snapshot function's name, so the two meet at the same items."""
    return hashlib.sha256(function_name.encode("utf-8")).hexdigest()[:SCOPE_CHARACTERS]


def stores_for(task: Mapping[str, Any], environ: Mapping[str, str] | None = None, *, table: Any = None) -> tuple[DynamoStateStore | None, DirtyStore | None, DirtyBatch | None]:
    """``(state store, dirty store, what changed)`` for a run in the Lambda.

    A task the trigger scheduled names ``incremental``: it gets all three. Any other run (started by hand, or by the interval rule) reads the whole
    corpus, and still gets the state store so that it leaves a state for the next incremental run. Without a lock table there is nothing to keep.
    """
    environment = os.environ if environ is None else environ
    scope = str(task.get(SCOPE_FIELD) or "") or (scope_of(environment[FUNCTION_NAME_ENVIRONMENT]) if environment.get(FUNCTION_NAME_ENVIRONMENT) else "")
    found = table if table is not None else lock_table_from_environment(environment)
    if not scope or found is None:
        return None, None, None
    if not task.get(INCREMENTAL_FIELD):
        return DynamoStateStore(found, scope), None, None
    dirty = DirtyStore(found, scope)
    return DynamoStateStore(found, scope), dirty, dirty.read()
