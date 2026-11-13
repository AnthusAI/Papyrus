"""The one definition of how a Story moves through the newsroom (docs/story-procedure.md).

Pure data and pure functions, no model calls. The CLI reads it for `papyrus stories next` and for the reminders printed after a write.
Each live step is also an item of the Story's stored checklist (story_checklist.py): a skipped step needs a recorded reason, and publishing
refuses while a required step is open. The four review steps are the template's readers' lenses. Human sign-off is never a stage: a person
comes in through a review request."""

from __future__ import annotations

import dataclasses
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable

from .content_item_lifecycle import CONTENT_ITEM_STAGES

LIVE = "live"
OFF = "off"
NOT_BUILT = "not_built"

DONE = "done"
NOT_DONE = "not_done"
UNKNOWN = "unknown"
SKIPPED = "skipped"
NOT_APPLICABLE = "not_applicable"
#: Recorded done, but against an earlier version of the Story than the current one (only versioned steps).
STALE = "stale"
CLOSED_STATES = (DONE, SKIPPED, NOT_APPLICABLE)

OUTLINE_KEY = "outline"
EDITOR_REVIEW_KEY = "editorReview"
STAGES_AT_OR_AFTER_COPYWRITING = ("copywriting", "illustration", "typesetting", "published")
EARLY_STAGES = ("idea", "assignment", "reporting")
STAGES_WITHOUT_NEXT_STEP = ("spiked", "held", "published")

#: Steps added after Stories were already published. A published Story that has no item for one is a record of what happened before the step existed, so it is
#: never listed as remaining; a revision of it (not published as such) gets the step like any draft.
ADDED_AFTER_PUBLISH_KEYS = ("illustration", "rated")

#: The version of this template. Raise it whenever a step is added, removed or changes its status, so each checklist item records the template it came from.
TEMPLATE_VERSION = 6


@dataclass(frozen=True)
class Step:
    key: str
    stage: str
    role: str
    title: str
    command: str
    status: str
    optional: bool
    note: str
    #: Done by hand: no record proves it, so marking it done needs a short findings note (the four review lenses).
    manual: bool = False
    #: Depends on the Story's text, so a done record is only good for the version it was recorded against: a newer version makes it stale.
    versioned: bool = False


STEPS: tuple[Step, ...] = (
    Step("choose", "idea", "Editor agent or a person", "Choose the idea", "papyrus ideas select --section <section>", LIVE, False,
         "The editor agent picks few, under a rate limit. A person can pick by hand with stories assign-research, or undo a pick by moving the Story back."),
    Step("direction", "assignment", "Editor", "Give the research direction",
         "papyrus stories assign-research --story {story} --direction-file direction.md", LIVE, False,
         "The direction is the Assignment's instructions."),
    Step("research", "reporting", "Reporter", "Research the Story",
         "papyrus assignments research-multi <assignment id>", LIVE, False,
         "The research packet is stored on the Assignment."),
    Step("outline", "reporting", "Editor agent", "Write the outline after the research",
         "papyrus stories outline --story {story}", LIVE, False,
         "A person can save their own with stories save-version --outline. A later version counts as the draft."),
    Step("draft", "copywriting", "Copywriter", "Write the draft",
         "papyrus stories draft --story {story}", LIVE, False,
         "A version newer than the outline; a person can save their own with stories save-version. Share a review link: after each save, show the editor the console link of the exact version (the console row of stories save-version, or papyrus links --story LINEAGE --version N), before asking for anything."),
    Step("fact_check", "copywriting", "Fact-check agent", "Fact-check the draft", "", NOT_BUILT, False,
         "Not built yet (PPY-719a02)."),
    Step("copy_edit", "copywriting", "Copywriter with Humanus", "Copy-edit the draft",
         "papyrus editorial check-version --item <current version id>", LIVE, False,
         "A finished editorial check of the current version with no error-level violation. Share a review link: show the editor the console link of the version you checked (and of any version the copy edit saves) before asking to publish.",
         versioned=True),
    Step("editor_review", "copywriting", "Editor agent", "Editor review", "", OFF, False,
         "Off: needs the editor_review.tac procedure, which no site has on."),
    Step("review_people", "copywriting", "Editor or reviewing agent", "Reviewed for readers",
         "papyrus stories step --story {story} --step review_people --state done --note <findings>", LIVE, False,
         "Human readers: a person or agent reads the Story as a reader would and records the findings. What each lens checks is a later design (PPY-59c772df).", True, versioned=True),
    Step("review_reader_agents", "copywriting", "Editor or reviewing agent", "Reviewed for AI reader agents",
         "papyrus stories step --story {story} --step review_reader_agents --state done --note <findings>", LIVE, False,
         "AI agents that read the page for a person. Findings are recorded by hand for now (PPY-59c772df).", True, versioned=True),
    Step("review_search", "copywriting", "Editor or reviewing agent", "Reviewed for search",
         "papyrus stories step --story {story} --step review_search --state done --note <findings>", LIVE, False,
         "Search crawlers. Findings are recorded by hand for now (PPY-59c772df).", True, versioned=True),
    Step("review_social", "copywriting", "Editor or reviewing agent", "Reviewed for social previews",
         "papyrus stories step --story {story} --step review_social --state done --note <findings>", LIVE, False,
         "Social previews (link cards). Run `papyrus stories lens-check --story {story} --lens social --static web`: it fetches the planned og:image (absolute HTTPS, status, Content-Type, format, size, shape). "
         "A WebP or AVIF, a small or oddly shaped picture, a missing, invalid or unreachable one is a warning or not verified, never a pass; make a JPEG or PNG share rendition and keep the modern format for the page. "
         "Also read title, description and picture together for relevance, legibility, alt text and misleading context. The findings note records the tested URL, format, dimensions and result, and any platform uncertainty "
         "(no result is proof a platform shows the card). After publishing, fetch the live page and check its og:image and twitter:image and the public picture; report CDN or platform cache staleness separately.", True, versioned=True),
    Step("concepts", "copywriting", "Editor or reviewing agent", "Associate with relevant Concepts",
         "papyrus stories link-concept --story {story} --concept \"Name\" --note <why>", LIVE, False,
         "Tag the Story with the existing accepted Concepts it is about (stories link-concept: exact names, never creates one). No Story command creates a Concept: make a missing one from a Reference "
         "(references link --reference <id> --concept NAME --create) or in the newsroom. Then mark this step done with a findings note that names the Concepts added and any considered and left out "
         "(papyrus stories step --story {story} --step concepts --state done --note <findings>), or skipped with a reason.", True),
    Step("related_content", "copywriting", "Editor or reviewing agent", "Add related associations",
         "papyrus stories suggest-links --story {story}", LIVE, False,
         "Read only: ranked related articles, posts and References from the Story's concepts, other than what the Story already links or cites. Add the good ones as see-also associations "
         "(stories link-story --story <lineage> --to <lineage>, and --reference <id> for a Reference). Then mark this step done with a findings note that says what was linked and what was left out and why "
         "(papyrus stories step --story {story} --step related_content --state done --note <findings>), or skipped with a reason.", True),
    Step("illustration", "illustration", "Editor, or an agent following the figures skill", "Illustrate",
         "papyrus stories save-version --story {story} --body-file draft.md --images ./pictures", LIVE, False,
         "Required for the Story types the site lists in its design-system setting illustrationRequiredTypes (articles by default). Done only when the records prove it: the current version has a cover "
         "(front matter image) that is a stored asset (no approval is required unless the site opts in with illustrationRequireApprovalCredit; an approval is recorded as metadata in the front matter coverImage record, never as a credit line; papyrus guide figures, "
         ".agents/skills/figures/SKILL.md), with its dark picture where the site requires dark figures. It cannot be marked done by hand. A person can record an exception instead: "
         "papyrus stories step --story {story} --step illustration --state skipped --reason <why>.", versioned=True),
    Step("rated", "illustration", "An editor", "Rate the Story",
         "papyrus stories set-stars --story {story} --stars <1-5>", LIVE, False,
         "Required only for a site that turns on the design-system setting publishRequiresRating (off by default; a site without it has no item for this step). Done only when the records prove it: "
         "the Story has an editor's star rating of 1 to 5 recorded by a person (a rating of 0 or a model's prediction does not count). It cannot be marked done, skipped or not applicable by hand; "
         "an editor rates the Story with papyrus stories set-stars."),
    Step("typesetting", "typesetting", "Editor", "Typeset", "", NOT_BUILT, True, "Not built yet."),
    Step("publish", "published", "A person", "Publish the Story", "papyrus ops content publish --id <item id>", LIVE, False,
         "The only hard gate."),
)


STEP_BY_KEY = {step.key: step for step in STEPS}
REVIEW_STEP_KEYS = tuple(step.key for step in STEPS if step.key.startswith("review_"))


@dataclass(frozen=True)
class Procedure:
    """The ordered steps of a Story's procedure: the engine's default (``STEPS``) or the site's own (``procedure_from_document``)."""

    steps: tuple[Step, ...]
    source: str = "default"   # "default" or "site"
    version: int | None = None   # the site document's catalog version

    @property
    def by_key(self) -> dict[str, Step]:
        return {step.key: step for step in self.steps}

    def spec(self) -> dict[str, Any] | None:
        """Plain data, so the facts of a Story stay JSON: None for the default."""
        return None if self.source == "default" else {"source": self.source, "version": self.version, "steps": [dataclasses.asdict(step) for step in self.steps]}

    @staticmethod
    def from_spec(spec: dict[str, Any] | None) -> "Procedure":
        if not spec:
            return DEFAULT_PROCEDURE
        return Procedure(tuple(Step(**row) for row in spec["steps"]), spec.get("source", "site"), spec.get("version"))


DEFAULT_PROCEDURE = Procedure(STEPS)
BUILT_IN_OVERRIDES = ("title", "role", "command", "note", "optional")
CUSTOM_FIELDS = ("key", "stage", "role", "title", "command", "note", "optional", "versioned")
PUBLISH_STEP_KEY = "publish"


def procedure_problems(document: Any) -> list[tuple[str, str]]:
    """(field path, message) for each problem with a site procedure document's ``steps``. Empty means it can be used."""
    if not isinstance(document, dict) or not isinstance(document.get("steps"), list) or not document["steps"]:
        return [("steps", "must be a non-empty list of steps")]
    problems, seen = [], set()
    for index, entry in enumerate(document["steps"]):
        where = f"steps[{index}]"
        key = entry.get("key") if isinstance(entry, dict) else None
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            problems.append((where, "needs a key of lowercase letters, digits and underscores"))
            continue
        if key in seen:
            problems.append((where, f"the step {key!r} appears twice"))
        seen.add(key)
        built_in = STEP_BY_KEY.get(key)
        allowed = BUILT_IN_OVERRIDES if built_in else CUSTOM_FIELDS
        for field in entry:
            if field != "key" and field not in allowed:
                problems.append((f"{where}.{field}", "cannot be changed on a built-in step" if built_in else "is not a field of a step"))
        for field in ("title", "role", "command", "note"):
            if field in entry and (not isinstance(entry[field], str) or not entry[field].strip()):
                problems.append((f"{where}.{field}", "must be text"))
        for field in ("optional", "versioned"):
            if field in entry and not isinstance(entry[field], bool):
                problems.append((f"{where}.{field}", "must be true or false"))
        if not built_in:
            if not isinstance(entry.get("title"), str) or not entry["title"].strip():
                problems.append((f"{where}.title", "a step of your own needs a title"))
            if entry.get("stage") not in CONTENT_ITEM_STAGES:
                problems.append((f"{where}.stage", f"a step of your own needs a stage, one of {', '.join(CONTENT_ITEM_STAGES)}"))
    if not problems and document["steps"][-1]["key"] != PUBLISH_STEP_KEY:
        problems.append(("steps", "must end with the publish step, the only hard gate"))
    return problems


def procedure_from_document(document: dict[str, Any], version: int | None = None) -> Procedure:
    """The site's procedure: its listed steps in its order. A built-in step keeps its status and its checks (only its words and whether it is optional can
    change); a step of the site's own is done by hand with a findings note, like a review step. A built-in step left out is not part of the site's procedure."""
    problems = procedure_problems(document)
    if problems:
        raise ValueError("The procedure document has problems: " + "; ".join(f"{path} {message}" for path, message in problems))
    steps = []
    for entry in document["steps"]:
        built_in = STEP_BY_KEY.get(entry["key"])
        if built_in:
            steps.append(dataclasses.replace(built_in, **{field: entry[field] for field in BUILT_IN_OVERRIDES if field in entry}))
        else:
            steps.append(Step(entry["key"], entry["stage"], entry.get("role", "Editor or reviewing agent"), entry["title"], entry.get("command", ""), LIVE, bool(entry.get("optional", False)),
                              entry.get("note", ""), manual=True, versioned=bool(entry.get("versioned", False))))
    return Procedure(tuple(steps), "site", version)


def procedure_of(client) -> Procedure:
    """The Story procedure of the site ``client`` is signed in to: its saved ``procedure`` document, else the default (the site saved none).

    One read (two index queries and a download) is kept on the client for a minute. A document that cannot be read raises: nothing guesses which procedure
    the site has, so a reminder is not computed and a Story is not published on the wrong list. A role that cannot read the site's documents does not ask."""
    import time

    kept = getattr(client, "_papyrus_story_procedure", None)
    if kept and time.monotonic() - kept[0] < 60:
        return kept[1]
    from .guidelines import GuidelineStore

    found = GuidelineStore(client).read("procedure")
    procedure = DEFAULT_PROCEDURE if found is None else procedure_from_document(found["document"], found["reference"].get("versionNumber"))
    try:
        client._papyrus_story_procedure = (time.monotonic(), procedure)
    except AttributeError:   # a client that cannot hold it reads again next time
        pass
    return procedure


def _metadata_of(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else {}
        except json.JSONDecodeError:
            value = {}
    return value if isinstance(value, dict) else {}


def story_facts(client, lineage: str, read_check_run: Callable[[str], dict[str, Any] | None] | None = None, *, read_cover: bool = True) -> dict[str, Any]:
    """Reads the records once: the current version, the lineage's Assignments with their direction and research packets, and the stored check run.

    The cover evidence (the version's media and the site's design-system settings) is read only from the copywriting stage on (``read_cover=False`` skips it
    anywhere): before a draft there is no cover to find, and the router and the research worker, which work on Stories then, run under roles that cannot read media.
    Until then the cover reads as missing, and the next change to the Story (an editor's, past that stage) reads the records."""
    from .assignments import assignment_metadata
    from .assignments_workflow import load_assignment_research_packet_entries
    from .story_reporting import _current_of, story_versions

    versions = story_versions(client, lineage)
    if not versions:
        raise ValueError(f"No story found for lineage {lineage}.")
    current = _current_of(versions)
    assignments = []
    for assignment in client.list_by_index("assignmentsByItemLineageAndCreatedAt", lineage):
        metadata = assignment_metadata(client, assignment)
        direction = metadata.get("direction") or assignment.get("instructions") or metadata.get("instructions")
        try:
            has_packet = bool(load_assignment_research_packet_entries(client, assignment["id"]))
        except Exception:
            has_packet = False
        assignments.append({"id": assignment["id"], "hasDirection": bool(str(direction or "").strip()), "hasResearchPacket": has_packet})
    illustration = None
    try:
        from .story_illustration import default_policy, inputs_for_item

        if read_cover and (current.get("stage") or "idea") not in EARLY_STAGES:
            illustration = inputs_for_item(client, current, _metadata_of(current))
        else:
            illustration = {"type": current.get("type"), "frontMatter": {}, "body": "", "mediaPaths": [], "policy": default_policy()}
    except Exception:  # noqa: BLE001 - the step then reads unknown instead of the Story failing to load
        illustration = None
    rating = None
    try:
        from .story_rating import inputs_for_item as rating_inputs, not_required

        rating = rating_inputs(client, current) if read_cover and (current.get("stage") or "idea") not in EARLY_STAGES else not_required()
    except Exception:  # noqa: BLE001 - the step then reads unknown instead of the Story failing to load
        rating = None
    check_run, check_run_error = None, False
    try:
        if read_check_run is None:
            from .editorial_commands import read_item_check_run as read_check_run
        check_run = read_check_run(current["id"])
    except Exception:
        check_run_error = True
    return {
        "procedureSpec": procedure_of(client).spec(),
        "lineage": lineage,
        "stage": current.get("stage") or "idea",
        "versionId": current["id"],
        "versionNumber": int(current.get("versionNumber") or 1),
        "body": current.get("bodyMarkus") or "",
        "metadata": _metadata_of(current),
        "assignments": assignments,
        "checkRun": check_run,
        "checkRunError": check_run_error,
        "illustration": illustration,
        "rating": rating,
        "versionTimes": {int(row.get("versionNumber") or 0): row.get("versionCreatedAt") for row in versions},
    }


def _check_run_finished(run: dict[str, Any]) -> bool:
    from .editorial_checks import FINISHED_LANE_STATUSES

    lanes = run.get("lanes")
    if not isinstance(lanes, dict):
        return False
    return all((lane or {}).get("status") in FINISHED_LANE_STATUSES for lane in lanes.values() if isinstance(lane, dict))


def _has_error_violation(run: dict[str, Any]) -> bool:
    return any(f.get("status") == "violation" and f.get("severity") == "error" for f in run.get("findings") or [])


def _state_of(step: Step, facts: dict[str, Any]) -> str:
    stage = facts["stage"]
    metadata = facts["metadata"]
    outline = metadata.get(OUTLINE_KEY)
    if step.key == "choose":
        return DONE if stage != "idea" else NOT_DONE
    if step.key == "direction":
        return DONE if any(a["hasDirection"] for a in facts["assignments"]) else NOT_DONE
    if step.key == "research":
        return DONE if any(a["hasResearchPacket"] for a in facts["assignments"]) else NOT_DONE
    if step.key == "outline":
        return DONE if outline else NOT_DONE
    if step.key == "draft":
        if isinstance(outline, dict) and outline.get("versionNumber") is not None:
            return DONE if facts["versionNumber"] > int(outline["versionNumber"]) else NOT_DONE
        return DONE if facts["body"].strip() and stage in STAGES_AT_OR_AFTER_COPYWRITING else NOT_DONE
    if step.key == "copy_edit":
        # A check of an idea or an outline is not a copy edit of the draft.
        if _state_of(STEP_BY_KEY["draft"], facts) != DONE:
            return NOT_DONE
        if facts["checkRunError"]:
            return UNKNOWN
        run = facts["checkRun"]
        if run and _check_run_finished(run) and not _has_error_violation(run):
            return DONE
        return NOT_DONE
    if step.key == "editor_review":
        review = metadata.get(EDITOR_REVIEW_KEY)
        approved = isinstance(review, dict) and review.get("versionId") == facts["versionId"] and review.get("verdict") == "approve"
        return DONE if approved else NOT_DONE
    if step.key == "illustration":
        from .story_illustration import cover_evidence

        return cover_evidence(facts.get("illustration"))[0]
    if step.key == "rated":
        from .story_rating import rating_evidence

        return rating_evidence(facts.get("rating"))[0]
    if step.key == "publish":
        return DONE if stage == "published" else NOT_DONE
    if step.manual:
        return NOT_DONE   # no record proves a lens review; the Story's stored checklist says whether a person or agent did it
    return UNKNOWN


def assess(facts: dict[str, Any], procedure: Procedure | None = None) -> dict[str, Any]:
    """Pure over facts: each step's state from the records (the evidence), the next step and the steps skipped before the Story's current stage.

    This is the evidence view, which the checklist sync reads. ``resolve`` lays the Story's stored checklist over it: that is the answer people read."""
    rows = []
    for step in (procedure or Procedure.from_spec(facts.get("procedureSpec"))).steps:
        rows.append({
            "key": step.key, "title": step.title, "role": step.role, "stage": step.stage, "status": step.status,
            "state": _state_of(step, facts), "command": step.command.replace("{story}", str(facts["lineage"])), "note": step.note,
            "optional": step.optional, "manual": step.manual, "versioned": step.versioned,
        })
    return _conclude(facts["stage"], rows)


def _conclude(stage: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    next_row = None
    skipped: list[dict[str, Any]] = []
    if stage not in STAGES_WITHOUT_NEXT_STEP:
        pending = [row for row in rows if row["state"] not in CLOSED_STATES]
        next_row = next((row for row in pending if row["status"] == LIVE), None) or (pending[0] if pending else None)
        current_index = CONTENT_ITEM_STAGES.index(stage) if stage in CONTENT_ITEM_STAGES else 0
        optional_keys = {row["key"] for row in rows if row["optional"]}
        skipped = [
            row for row in rows
            if row["state"] == NOT_DONE and row["status"] == LIVE and row["key"] not in optional_keys
            and CONTENT_ITEM_STAGES.index(row["stage"]) < current_index
        ]
    return {"stage": stage, "steps": rows, "next": next_row, "skipped": skipped}


def recorded_version(row: dict[str, Any], version_times: dict[int, Any]) -> tuple[int | None, str]:
    """The Story version a stored step was recorded against, and how we know. A step written since staleness was introduced carries it; an older
    record is placed by its time among the Story's version times; failing both, the version is unknown."""
    if row.get("storyVersion") is not None:
        return int(row["storyVersion"]), "recorded"
    changed = row.get("changedAt")
    earlier = [number for number, at in (version_times or {}).items() if at and changed and str(at) <= str(changed)]
    if earlier:
        return max(earlier), "inferred from the time it was recorded"
    return None, "unknown"


def resolve(assessment: dict[str, Any], stored: list[dict[str, Any]], facts: dict[str, Any]) -> dict[str, Any]:
    """The one answer: the Story's stored checklist decides every step it has an item for; the records only add a ``hint``.

    * a stored ``done``, ``skipped`` or ``not_applicable`` is that state; a stored ``open`` is ``not_done``;
    * a ``done`` of a versioned step (a review lens, the copy edit) recorded against an earlier version is ``stale`` and still remains to do;
    * a step with no stored item (a new template step, or no checklist yet) falls back to what the records prove;
    * ``evidence`` keeps what the records say; ``hint`` is set only where that differs from the answer.

    Adds ``remaining`` (live, required steps not closed, in template order, publishing last), ``blocking`` (those other than publishing that are
    open), ``stale`` and ``status`` (``complete``, ``ready``, ``blocked`` or ``stale``). Returns a new assessment; the argument is not changed."""
    by_key = {row["stepKey"]: row for row in stored}
    current = int(facts["versionNumber"])
    rows = []
    for source in assessment["steps"]:
        row = {**source, "evidence": source["state"], "source": "evidence", "recordedVersion": None, "recordedBasis": None, "freshness": None, "hint": None}
        item = by_key.get(row["key"])
        if item is not None:
            row["source"] = "checklist"
            row["state"] = {"done": DONE, "skipped": SKIPPED, "not_applicable": NOT_APPLICABLE}.get(item.get("state"), NOT_DONE)
            number, basis = recorded_version(item, facts.get("versionTimes") or {})
            row["recordedVersion"], row["recordedBasis"] = number, basis
            if row["versioned"] and row["state"] == DONE and number != current:
                recorded = f"v{number}" if number is not None else "an unknown version"
                if not row["manual"] and row["evidence"] == DONE:   # the records prove this step for the current version itself (a passing copy-edit check)
                    row["freshness"] = f"current (recorded against {recorded}; the records prove it for v{current})"
                else:
                    row["state"] = STALE
                    row["freshness"] = f"STALE: recorded against {recorded}, story is now v{current}"
            elif number == current:
                row["freshness"] = "current"
            elif number is None:
                row["freshness"] = "current (the version it was recorded against is unknown)"
            elif row["versioned"]:
                row["freshness"] = f"current (recorded against v{number}; a {row['state'].replace('_', ' ')} answer is not tied to one version)"
            else:
                row["freshness"] = f"current (recorded against v{number}; this step does not depend on one version)"
            if not row["manual"] and row["evidence"] in (DONE, NOT_DONE):
                if row["evidence"] == DONE and row["state"] not in CLOSED_STATES:
                    row["hint"] = "the records show this is done; the next write to the Story records it on the checklist"
                elif row["evidence"] == NOT_DONE and row["state"] == STALE:
                    row["hint"] = "the records do not show it for the current version either"
        if row["evidence"] == NOT_APPLICABLE and row["state"] == NOT_DONE:   # the Story's type does not need this step (the type changed after the item was made)
            row["state"] = NOT_APPLICABLE
        row["historic"] = bool(
            assessment["stage"] == "published" and item is None and row["key"] in ADDED_AFTER_PUBLISH_KEYS and row["evidence"] != DONE
        )
        if row["historic"]:
            row["hint"] = "published before this step existed; it is not required of the published record (a revision must close it)"
        rows.append(row)
    resolved = _conclude(assessment["stage"], rows)
    live = [row for row in rows if row["status"] == LIVE and not row["optional"] and not row["historic"]]
    remaining = [] if assessment["stage"] in ("spiked", "held") else [row for row in live if row["state"] not in CLOSED_STATES]
    blocking = [row for row in remaining if row["key"] != "publish" and row["state"] == NOT_DONE]
    stale = [row for row in remaining if row["state"] == STALE]
    status = "blocked" if blocking else "stale" if stale else "ready" if remaining else "complete"
    if assessment["stage"] not in STAGES_WITHOUT_NEXT_STEP:
        resolved["next"] = remaining[0] if remaining else None   # the first thing still to do; a step that is off or not built is never next
    return {**resolved, "remaining": remaining, "blocking": blocking, "stale": stale, "status": status}


def status_text(resolved: dict[str, Any]) -> str:
    remaining, blocking, stale = resolved["remaining"], resolved["blocking"], resolved["stale"]
    names = lambda items: ", ".join(row["key"] for row in items)  # noqa: E731
    if resolved["status"] == "complete":
        return "nothing remains"
    if resolved["status"] == "blocked":
        text = f"{len(remaining)} remain; publishing is blocked by {len(blocking)} open required step(s): {names(blocking)}"
        return text + (f"; stale: {names(stale)}" if stale else "")
    if resolved["status"] == "stale":
        return f"{len(remaining)} remain; none is open, but {len(stale)} recorded step(s) are stale and need doing again for this version: {names(stale)}"
    return f"{len(remaining)} remain; only publishing is left"


def process_text(assessment: dict[str, Any]) -> str:
    """The procedure as an agent reads it in its context pack: where the Story is, what is done, what is next and what comes after."""
    def named(row: dict[str, Any]) -> str:
        return row["key"] + ({OFF: " (off)", NOT_BUILT: " (not built)"}.get(row["status"], ""))

    rows = assessment["steps"]
    upcoming = [row for row in rows if row["state"] != DONE and row is not assessment["next"]]
    next_row = assessment["next"]
    lines = [f"Stage: {assessment['stage']}",
             "Done: " + (", ".join(row["key"] for row in rows if row["state"] == DONE) or "nothing yet"),
             f"Next: {next_row['title']} ({next_row['role']})" if next_row else "Next: nothing; the Story is not in progress"]
    if next_row and upcoming:
        lines.append("Not done: " + ", ".join(named(row) for row in upcoming))
    if assessment["skipped"]:
        lines.append("Skipped earlier: " + ", ".join(row["key"] for row in assessment["skipped"]))
    return "\n".join(lines)


def _command_text(row: dict[str, Any]) -> str:
    if row["status"] == OFF:
        return f"off: {row['note']}"
    if row["status"] == NOT_BUILT:
        return f"not built: {row['note']}"
    return row["command"]


def next_lines(assessment: dict[str, Any]) -> list[str]:
    lines = []
    row = assessment["next"]
    if row:
        lines.append("\t".join(["next", row["key"], row["role"], row["title"], _command_text(row)]))
    for skipped in assessment["skipped"]:
        lines.append("\t".join(["skipped", skipped["key"], skipped["title"]]))
    return lines


def status_lines(resolved: dict[str, Any]) -> list[str]:
    return ["\t".join(["status", resolved["status"], str(len(resolved["remaining"])), status_text(resolved)])]


def version_lines(resolved: dict[str, Any]) -> list[str]:
    """One line per step with a stored item: the version it was recorded against, how we know, and ``current`` or ``STALE: ...``."""
    lines = []
    for row in resolved["steps"]:
        if row.get("source") != "checklist":
            continue
        recorded = f"recorded against v{row['recordedVersion']} ({row['recordedBasis']})" if row["recordedVersion"] is not None else "recorded against an unknown version"
        lines.append("\t".join(["version", row["key"], recorded, row["freshness"] or ""]))
    return lines


def hint_lines(resolved: dict[str, Any]) -> list[str]:
    return ["\t".join(["hint", row["key"], row["hint"]]) for row in resolved["steps"] if row.get("hint")]


def remaining_lines(resolved: dict[str, Any]) -> list[str]:
    """One line per step still to do, in order: the single list of what remains. The first is the ``next`` line."""
    return ["\t".join(["remaining", row["key"], "stale" if row["state"] == STALE else "open", row["title"], _command_text(row)]) for row in resolved["remaining"]]


def step_lines(assessment: dict[str, Any]) -> list[str]:
    return ["\t".join(["step", row["key"], row["state"], row["status"], row["stage"], row["role"], row["title"]]) for row in assessment["steps"]]


def reminder_assessment(client, lineage: str, read_check_run=None, *, sync_checklist: bool = False) -> dict[str, Any] | None:
    """The assessment for a reminder after a write; a failure prints one line to stderr and returns None, never raises.

    ``sync_checklist`` is for a reminder printed after a write: the same facts then bring the Story's stored checklist up to date once
    (new template steps open, evidence marks steps done). It never fails the write either; a problem prints one line to stderr."""
    try:
        facts = story_facts(client, lineage, read_check_run)
        assessment = assess(facts)
    except Exception as error:
        print(f"next\tnot computed\t{type(error).__name__}: {str(error)[:160]}", file=sys.stderr)
        return None
    if sync_checklist:
        from .story_checklist import sync_quietly

        sync_quietly(client, lineage, facts=facts, assessment=assessment)
    try:   # the stored checklist decides; if it cannot be read, the reminder falls back to the records
        from .story_checklist import read_steps

        return resolve(assessment, read_steps(client, lineage), facts)
    except Exception:  # noqa: BLE001
        return assessment


def print_reminder(client, lineage: str, read_check_run=None) -> dict[str, Any] | None:
    assessment = reminder_assessment(client, lineage, read_check_run, sync_checklist=True)
    print_next_lines(assessment)
    return assessment


def next_payload(assessment: dict[str, Any] | None) -> dict[str, Any] | None:
    if assessment is None:
        return None
    return {"next": assessment["next"], "skipped": assessment["skipped"]}


def warn_skipped(assessment: dict[str, Any]) -> None:
    """One stderr line naming each skipped step, for a move to a later stage."""
    for row in assessment["skipped"]:
        print(f"warning: step '{row['key']}' ({row['title']}) was skipped; the Story moved anyway.", file=sys.stderr)


def print_next_lines(assessment: dict[str, Any] | None) -> None:
    if assessment is not None:
        for line in next_lines(assessment):
            print(line)
