"""Keeping the site cyclotron's classifiers in parity with the newsroom's Sections.

The Section list is maintained by the normal Section curation procedures. Before
each sweep the stored cyclotron's active classifiers are compared with the ones
the current Section list calls for: a new Section gets a classifier, a removed
or disabled Section has its classifier retired (its labels stay in the store),
and the selector is replaced whenever the set of Sections it chooses among
changes. Nothing here calls a model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .site_cyclotron import SECTION_FIT_CLASSIFIER_PREFIX, is_section_selector_classifier_id

SITE_CLASSIFIER_SET_AUTHOR = "papyrus: section parity"
STORE_FILE_NAME = "cyclotron.sqlite3"


@dataclass(frozen=True)
class SiteClassifierSetPlan:
    added: tuple[Any, ...] = ()
    retired: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()

    @property
    def unchanged(self) -> bool:
        return not self.added and not self.retired

    def to_json(self) -> dict[str, Any]:
        return {"added": [spec.id for spec in self.added], "retired": list(self.retired), "kept": list(self.kept)}

    def describe(self) -> list[str]:
        def readable(identifier: str) -> str:
            if identifier.startswith(SECTION_FIT_CLASSIFIER_PREFIX):
                return f"Section {identifier.removeprefix(SECTION_FIT_CLASSIFIER_PREFIX)}"
            return "the Section selector" if is_section_selector_classifier_id(identifier) else identifier

        lines = [f"add the classifier for {readable(spec.id)} ({spec.id})" for spec in self.added]
        lines += [f"retire the classifier for {readable(identifier)} ({identifier}); its labels stay in the store"
                  for identifier in self.retired]
        return lines


def plan_site_classifier_set(stored_specs: Sequence[Any] | None, desired_specs: Sequence[Any]) -> SiteClassifierSetPlan:
    """What must change so the stored active classifiers equal the desired ones. No store yet means nothing to change."""
    if stored_specs is None:
        return SiteClassifierSetPlan(kept=tuple(spec.id for spec in desired_specs))
    stored_by_id = {spec.id: spec for spec in stored_specs}
    desired_by_id = {spec.id: spec for spec in desired_specs}
    for identifier in stored_by_id.keys() & desired_by_id.keys():
        if stored_by_id[identifier] != desired_by_id[identifier]:
            raise ValueError(f"classifier {identifier!r} is stored with a different question or labels than the Sections now imply")
    return SiteClassifierSetPlan(
        added=tuple(spec for spec in desired_specs if spec.id not in stored_by_id),
        retired=tuple(spec.id for spec in stored_specs if spec.id not in desired_by_id),
        kept=tuple(spec.id for spec in desired_specs if spec.id in stored_by_id))


def stored_active_specs(store_directory: str | Path) -> list[Any] | None:
    """The classifiers the stored cyclotron currently has, or None when there is no store yet."""
    from decision_flywheel.classifier_set import spec_from_record
    from decision_flywheel.embedded_storage import SQLiteEmbeddedStorage

    store_path = Path(store_directory) / STORE_FILE_NAME
    if not store_path.exists():
        return None
    saved = SQLiteEmbeddedStorage(store_path).meta("definition")
    if not saved:
        return None
    return [spec_from_record(record) for record in json.loads(saved[0])["definition"]["classifiers"]]


def definition_with_classifiers(definition, specs: Sequence[Any]):
    return replace(definition, classifiers=tuple(specs))


async def apply_site_classifier_set(cyclotron, plan: SiteClassifierSetPlan, seed_rubrics: Mapping[str, str],
                                    *, changed_by: str = SITE_CLASSIFIER_SET_AUTHOR) -> None:
    if plan.added:
        await cyclotron.add_classifiers(
            plan.added, added_by=changed_by,
            seed_rubrics={spec.id: seed_rubrics[spec.id] for spec in plan.added if spec.id in seed_rubrics})
    if plan.retired:
        await cyclotron.retire_classifiers(plan.retired, retired_by=changed_by)
