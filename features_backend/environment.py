from __future__ import annotations

import importlib.util

REQUIRES_CYCLOTRON_TAG = "requires-cyclotron"
CYCLOTRON_MODULE = "decision_flywheel"


def before_scenario(context, scenario):
    if REQUIRES_CYCLOTRON_TAG in scenario.effective_tags and importlib.util.find_spec(CYCLOTRON_MODULE) is None:
        scenario.skip("decision_flywheel not installed (poetry install --with cyclotron)")
