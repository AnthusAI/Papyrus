"""A backend that lacks a model is an error (features_backend/no-fallbacks-missing-models.feature). The GraphQL client is a stand-in."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import categories_commands, newsroom_commands, records  # noqa: E402


class _BackendWithoutModel:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def list_records(self, name: str, *args, **kwargs):
        if name == self.model_name:
            raise RuntimeError(f"Validation error of type FieldUndefined: Field 'list{name}s' in type 'Query' is undefined")
        return []

    def get_record(self, *args, **kwargs):
        raise RuntimeError(f"Validation error of type FieldUndefined: Field 'get{self.model_name}' in type 'Query' is undefined")


def held(context) -> SimpleNamespace:
    if not hasattr(context, "missingmodel"):
        context.missingmodel = SimpleNamespace(client=None, error=None, path=None)
    return context.missingmodel


@given("a backend that does not define the {model} model")
def _backend(context, model):
    held(context).client = _BackendWithoutModel(model)


@when("the owners of Reference attachments are looked up")
def _owners(context):
    state = held(context)
    try:
        newsroom_commands._load_model_attachment_owner_ids(state.client, [{"ownerKind": "reference"}])
    except Exception as error:  # the scenario asserts on it
        state.error = error


@when("the lexical steering configuration is applied")
def _apply(context):
    state = held(context)
    try:
        categories_commands.apply_lexical_steering_config(state.client, {})
    except Exception as error:
        state.error = error


@when("the lexical steering rules are exported")
def _export(context):
    state = held(context)
    state.path = Path(tempfile.mkdtemp()) / "lexical.json"
    try:
        categories_commands.write_lexical_steering_export(state.client, str(state.path), {})
    except Exception as error:
        state.error = error


@then("the lookup stops with the backend's FieldUndefined error")
@then("the import stops with the backend's FieldUndefined error")
def _stops(context):
    error = held(context).error
    assert error is not None and "FieldUndefined" in str(error), f"expected the backend's error, got {error!r}"


@then("the export stops with the backend's FieldUndefined error and no export file is written")
def _export_stops(context):
    state = held(context)
    assert state.error is not None and "FieldUndefined" in str(state.error), f"expected the backend's error, got {state.error!r}"
    assert not state.path.exists(), "an export file was written"


@then("the records module keeps no optional-model tolerance")
def _no_tolerance(context):
    for name in ("OPTIONAL_SCHEMA_MODELS", "is_missing_graphql_model_error", "build_record_changes_tolerating_optional_models"):
        assert not hasattr(records, name), name
