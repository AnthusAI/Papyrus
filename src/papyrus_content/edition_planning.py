from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from papyrus_newsroom.coverage_theme import editions_plan as newsroom_editions_plan

from .env import PAPYRUS_ROOT
from .graphql_authoring import PapyrusGraphQLAuthoringClient
from .options import normalize_string, parse_comma_list
from .steering import default_corpus_key

RESEARCH_EDITION_ASSIGNMENT_TYPE = "research.edition-candidate"
REPORTING_EDITION_ASSIGNMENT_TYPE = "reporting.edition-candidate"


def load_edition_planning_state(client: PapyrusGraphQLAuthoringClient) -> dict[str, Any]:
    return {
        "editions": client.safe_list_records("Edition"),
        "publishedEditions": client.safe_list_records("PublishedEdition"),
        "editionItems": client.safe_list_records("EditionItem"),
        "editionSlots": client.safe_list_records("EditionSlot"),
        "categorySets": client.safe_list_records("CategorySet"),
        "categories": client.safe_list_records("Category"),
        "references": client.safe_list_records("Reference"),
        "semanticRelations": client.safe_list_records("SemanticRelation"),
        "semanticNodes": client.safe_list_records("SemanticNode"),
        "assignments": client.safe_list_records("Assignment"),
        "assignmentEvents": client.safe_list_records("AssignmentEvent"),
        "newsroomSections": client.safe_list_records("NewsroomSection"),
    }


def build_edition_planning_plan(state: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    del state
    edition_date = normalize_string(options.get("editionDate"))
    if not edition_date:
        raise ValueError("Edition planning requires editionDate.")
    sections = parse_comma_list(options.get("sectionTargets") or options.get("sections")) or []
    section_budgets = _parse_section_budgets(options.get("sectionBudgets"))
    if not section_budgets:
        default_slots = int(options.get("publicationSlots") or 1)
        section_budgets = {section: default_slots for section in sections}
    corpus_key = normalize_string(options.get("corpusKey")) or default_corpus_key()
    signal_topic = normalize_string(options.get("topic")) or normalize_string(options.get("focusCategories")) or corpus_key
    coverage_key = normalize_string(options.get("coverageKey")) or f"coverage.{signal_topic.replace(' ', '-').lower()}"

    payload = newsroom_editions_plan(
        date=edition_date,
        sections=list(section_budgets.keys()) or sections or ["general"],
        section_budgets=section_budgets or {"general": 1},
        corpus_key=corpus_key,
        category_key=normalize_string(options.get("categoryKey")) or "",
        topic=signal_topic,
        coverage_key=coverage_key,
        theme_limit=int(options.get("maxAssignments") or 3),
        run_id=normalize_string(options.get("runId")) or "",
        apply=False,
        now=normalize_string(options.get("now")) or "",
    )

    records = payload.get("records") or []
    create_count = sum(1 for record in records if record.get("action") == "create")
    update_count = sum(1 for record in records if record.get("action") == "update")
    noop_count = sum(1 for record in records if record.get("action") == "noop")
    assignment_records = [record.get("expected") or {} for record in records if record.get("modelName") == "Assignment"]
    return {
        "generatedAt": _utc_now(),
        "editionDate": edition_date,
        "edition": {
            "id": f"edition-{edition_date}",
            "slug": normalize_string(options.get("editionSlug")) or edition_date,
            "status": "draft",
        },
        "categorySet": {},
        "sections": list(section_budgets.keys()) or sections,
        "assignments": assignment_records,
        "records": records,
        "summary": {
            "assignmentTypeKey": options.get("assignmentTypeKey") or RESEARCH_EDITION_ASSIGNMENT_TYPE,
            "contextBackedAssignmentCount": len(assignment_records),
            "createCount": create_count,
            "updateCount": update_count,
            "noopCount": noop_count,
            "sectionBudgets": [
                {"section": {"id": key, "type": "floating"}, "slots": value}
                for key, value in section_budgets.items()
            ],
        },
        "warnings": payload.get("warnings") or [],
        "desks": [
            {
                "categoryKey": theme.get("categoryKey") or theme.get("coverageKey"),
                "opportunityScore": theme.get("summary", {}).get("coverageThemeCount", 0),
                "referenceCount": theme.get("summary", {}).get("acceptedReferenceCount", 0),
                "signalCount": 1,
            }
            for theme in payload.get("coverageThemes") or []
        ],
        "focusCoverage": [],
        "raw": payload,
    }


def verify_edition_planning_plan(state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    assignment_ids = {assignment.get("id") for assignment in plan.get("assignments") or [] if assignment.get("id")}
    existing_ids = {assignment.get("id") for assignment in state.get("assignments") or [] if assignment.get("id")}
    missing = sorted(assignment_ids - existing_ids)
    return {"ok": not missing, "failures": [f"missing assignment {assignment_id}" for assignment_id in missing]}


def apply_edition_planning_plan(client: PapyrusGraphQLAuthoringClient, plan: dict[str, Any]) -> dict[str, Any]:
    actionable = [record for record in plan.get("records") or [] if record.get("action") != "noop"]
    applied = 0
    for record in actionable:
        client.upsert(record["modelName"], record["expected"])
        applied += 1
        if applied == len(actionable) or applied % 25 == 0:
            print(f"edition-planning\tapply\t{applied}/{len(actionable)}", flush=True)
    return {"applied": applied, "skipped": len(plan.get("records") or []) - len(actionable)}


def write_edition_planning_report(
    plan: dict[str, Any],
    payload: dict[str, Any],
    *,
    output_dir: str | None = None,
    filename: str = "edition-planning-report.json",
) -> dict[str, str]:
    run_id = f"edition-planning-{plan.get('editionDate')}-{timestamp_for_path(plan.get('generatedAt') or _utc_now())}"
    target_dir = Path(output_dir) if output_dir else PAPYRUS_ROOT / ".papyrus-runs" / run_id
    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = target_dir / filename
    filepath.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"outputDir": str(target_dir), "filepath": str(filepath)}


def build_edition_planning_command_plan(
    client: PapyrusGraphQLAuthoringClient,
    options: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    edition_date = normalize_string(options.get("date"))
    if not edition_date:
        raise ValueError("editions plan/dispatch-research requires --date YYYY-MM-DD.")
    state = load_edition_planning_state(client)
    assignment_type = options.get("assignment-type")
    plan = build_edition_planning_plan(
        state,
        {
            "editionDate": edition_date,
            "editionSlug": options.get("slug"),
            "assignmentTypeKey": REPORTING_EDITION_ASSIGNMENT_TYPE if assignment_type == "reporting" else assignment_type,
            "topDeskCount": options.get("top-desks"),
            "publicationSlots": options.get("slots"),
            "overassignmentRatio": options.get("ratio"),
            "maxAssignments": options.get("max-assignments"),
            "rotatingSectionCount": options.get("rotating-sections"),
            "focusCategories": parse_comma_list(options.get("focus-categories") or options.get("track-lenses")),
            "sectionTargets": parse_comma_list(options.get("section-targets")),
            "sectionBudgets": parse_comma_list(options.get("section-budgets")),
            "contextProfile": options.get("context-profile"),
            "targetSystemType": options.get("target-system-type"),
            "categoryKey": options.get("category-key"),
            "corpusKey": options.get("corpus-key"),
        },
    )
    report = write_edition_planning_report(
        plan,
        {"mode": "dry-run", "plan": plan},
        output_dir=options.get("output"),
        filename="dry-run-plan.json",
    )
    return plan, report


def print_edition_planning_summary(plan: dict[str, Any], report: dict[str, str], mode: str) -> None:
    summary = plan.get("summary") or {}
    category_set = plan.get("categorySet") or {}
    print(f"edition-planning\tmode\t{mode}")
    print(
        f"edition-planning\tedition\t{plan['edition']['id']}\t{plan['edition']['slug']}\t{plan['edition']['status']}"
    )
    print(f"edition-planning\tassignment-type\t{summary.get('assignmentTypeKey')}")
    print(f"edition-planning\tcategory-set\t{category_set.get('id')}\t{category_set.get('displayName')}")
    print(f"edition-planning\tdesks\t{len(plan.get('desks') or [])}")
    print(f"edition-planning\tsections\t{','.join(plan.get('sections') or []) or 'none'}")
    print(f"edition-planning\tassignments\t{len(plan.get('assignments') or [])}")
    print(f"edition-planning\tcontext-backed\t{summary.get('contextBackedAssignmentCount')}")
    print(
        f"edition-planning\trecords\tcreate={summary.get('createCount')}\t"
        f"update={summary.get('updateCount')}\tnoop={summary.get('noopCount')}"
    )
    print(f"edition-planning\treport\t{report['filepath']}")
    for warning in plan.get("warnings") or []:
        print(f"edition-planning\twarning\t{warning}")
    for budget in summary.get("sectionBudgets") or []:
        section = budget.get("section") or {}
        print(f"section-budget\t{section.get('id')}\tslots={budget.get('slots')}\ttype={section.get('type')}")
    for desk in plan.get("desks") or []:
        print(
            f"desk\t{desk.get('categoryKey')}\t{desk.get('opportunityScore')}\t"
            f"refs={desk.get('referenceCount')}\tsignals={desk.get('signalCount')}"
        )


def timestamp_for_path(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit() or ch in {"T", "Z"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_section_budgets(raw: Any) -> dict[str, int]:
    if isinstance(raw, dict):
        return {str(key): int(value) for key, value in raw.items()}
    budgets: dict[str, int] = {}
    for token in raw or []:
        text = str(token)
        if ":" not in text:
            continue
        key, value = text.split(":", 1)
        key = key.strip()
        if not key:
            continue
        try:
            budgets[key] = max(int(value.strip()), 0)
        except ValueError:
            continue
    return budgets
