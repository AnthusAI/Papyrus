"""``papyrus pod load``: put a pod's notes into the signed-in site's newsroom as private data, and ``papyrus pod build``'s refusal of a private pod.

One way, files to the newsroom. A load runs ``pod check`` first and refuses a pod with problems, except a rating of 5, which the check reports and the
load handles by its own rule: the rating is refused, the note still loads, and it is listed as a five-star candidate for a person to confirm.

What a note becomes is the newsroom's content item. The note's ``type`` is the Item's ``type`` (``papyrus:Article`` is ``article``), its ``stage`` the Item's
``stage`` (a note with none is at ``copywriting``, where every file-made Item starts), its ``section`` link the Item's ``section``. The other lifecycle keys land
on ``metadata.pod`` under the names the note uses, with the note's id and the commit it came from. They are claims (``papyrus_content/pod_claims.py``):
the newsroom's gates read its own records and never these. A load writes one version of a changed note, never a replay of its Git history, writes nothing
for a note that has not changed, never touches a note a person has since changed in the newsroom, and never publishes: a note at ``stage: published`` is
recorded at that stage and no page is made.

Only notes of a class that is an Item (Article, Post, Page) are loaded by this version. Notes of the other classes are counted and named in the report.
"""
from __future__ import annotations

import datetime
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from papyrus_content.ids import hash_short, hash_stable
from papyrus_content.markus_renderer.build import slugify
from papyrus_content.markus_renderer.content_markup import split_front_matter
from papyrus_content.markus_renderer.derive import derive_body
from papyrus_content.operator_errors import OperatorError
from papyrus_content.pod_claims import CLAIM_KEYS, FIVE_STAR_CANDIDATE, POD_METADATA_KEY, pod_record
from papyrus_content.publishing import ItemFields, save_item
from papyrus_content.story_reporting import save_story_version, story_versions
from papyrus_content.tenancy import tenant_scoped_item_id

from . import profile
from .check import FIVE_STAR_CANDIDATE as FIVE_STAR_CODE, POD_LEVEL, check_pod
from .notes import Note, walk

LOAD_ACTOR = "pod-load"
SITE_SETTINGS = Path("web") / "projection.json"
DEFAULT_STAGE = "copywriting"
ITEM_CLASSES = {"Article": "article", "Post": "post", "Page": "page"}
GIT_TIMEOUT_SECONDS = 30

CREATED, UPDATED, UNCHANGED, NEWSROOM_OWNED = "created", "updated", "unchanged", "now owned by the newsroom"


def has_site(pod: Path) -> bool:
    """A pod belongs to a site when it has a ``web/`` folder with the site's settings, ``web/projection.json``. Every other pod is private."""
    return (pod / SITE_SETTINGS).is_file()


def private_pod_message(pod: Path, command: str) -> str:
    return (f"{pod} is a private pod: it has no {SITE_SETTINGS.as_posix()} to name a site, so papyrus pod {command} refuses it and nothing is built or published. "
            f"A private pod is for `papyrus pod load`, which loads its notes as private newsroom data.")


def refuse_private(pod: Path, command: str) -> None:
    if not has_site(pod):
        raise OperatorError(private_pod_message(pod, command))


@dataclass
class PlannedNote:
    path: str
    note_id: str
    lineage: str
    action: str = ""
    fields: ItemFields | None = None
    stage: str = ""
    section: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    five_star_candidate: bool = False


@dataclass
class Plan:
    pod: Path
    commit: str
    private: bool
    notes: list[PlannedNote] = field(default_factory=list)
    skipped_classes: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    client: Any = None      # opened only for a pod that passed the check: a pod with problems never signs in


def commit_of(pod: Path) -> str:
    """The commit the pod is at. A load records it, so what is loaded must be exactly what that commit holds: a pod outside Git, with no commit, or with
    changes that are not committed is refused rather than loaded under a commit that does not describe it."""
    def git(*arguments: str) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(["git", "-C", str(pod), *arguments], capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise OperatorError(f"papyrus pod load could not run git in {pod} ({error}); a load records the commit it came from. Nothing was loaded.") from error

    head = git("rev-parse", "HEAD")
    if head.returncode != 0:
        raise OperatorError(f"{pod} is not a git repository with a commit; a load records the commit it came from. Commit the pod, then load it. Nothing was loaded.")
    changed = git("status", "--porcelain", "--untracked-files=all", "--", ".")
    if changed.returncode != 0 or changed.stdout.strip():
        raise OperatorError(f"{pod} has changes that are not committed; a load records the commit it came from, so commit them first. Nothing was loaded.")
    return head.stdout.strip()


def _class_of(note: Note) -> str:
    return str((note.front or {}).get("type") or "").removeprefix(profile.CLASS_PREFIX)


def _text(value: Any) -> str:
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return str(value)


def _section_of(note: Note, notes: list[Note]) -> str | None:
    """The section a note's ``section`` link names, as the Section note's file name made into a slug. The check has already shown the link names one note."""
    link = (note.front or {}).get("section")
    if not isinstance(link, str) or not link.startswith("[["):
        return None
    name = link[2:-2].split("|", 1)[0].strip()
    matches = [other for other in notes if other.path.removesuffix(".md") == name or other.path.removesuffix(".md").endswith("/" + name)]
    return slugify(matches[0].stem) if len(matches) == 1 else None


def _claims_of(front: dict[str, Any]) -> dict[str, Any]:
    return {key: (front[key] if key == "rating" else _text(front[key])) for key in CLAIM_KEYS if key in front and not (key == "rating" and front[key] == 5)}


def lineage_for(note_id: str, tenant_id: str | None) -> str:
    """The lineage a note's Item has, made from the note's permanent id alone, so a note is found again through the lineage index and never by a scan."""
    return tenant_scoped_item_id(tenant_id, f"pod-{hash_short(note_id)}")


def _loaded_hash(note_id: str, class_name: str, stage: str, section: str | None, front_matter_yaml: str, body: str) -> str:
    return "sha256:" + hash_stable({"id": note_id, "class": class_name, "stage": stage, "section": section, "frontMatter": front_matter_yaml, "body": body})


def plan_load(pod: Path, commit: str, tenant_id: str | None, open_client) -> Plan:
    """Read the pod and the newsroom (``open_client`` signs in, once the pod has passed the check), and decide for each Item note whether it is created, updated, unchanged or now owned by the newsroom. Writes nothing."""
    plan = Plan(pod, commit, private=not has_site(pod))
    report = check_pod(pod)
    plan.problems = [f"{'' if problem.path == POD_LEVEL else problem.path + ': '}{problem.message}" for problem in report.problems if problem.code != FIVE_STAR_CODE]
    if report.level == 0 and not plan.problems:
        plan.problems.append(f"{pod} is a level 0 pile with no {profile.CONTEXT_FILE}: its notes have no permanent ids, so nothing can be loaded; run `papyrus pod init` and type the notes first")
    if plan.problems:
        return plan
    client = plan.client = open_client()
    notes = [note for note in walk(pod) if note.typed and note.path.split("/", 1)[0] != "guidelines"]
    for note in notes:
        front = note.front or {}
        class_name = _class_of(note)
        if class_name not in ITEM_CLASSES:
            plan.skipped_classes[class_name or "untyped"] = plan.skipped_classes.get(class_name or "untyped", 0) + 1
            continue
        text = (pod / note.path).read_text(encoding="utf-8")
        front_matter_yaml, body = split_front_matter(text)
        front_matter_yaml = front_matter_yaml.lstrip("\n")
        derivation = derive_body(front_matter_yaml, body)
        if not derivation.ok:
            plan.problems.extend(f"{note.path}: {error.code}: {error.message}" for error in derivation.errors)
            continue
        note_id = str(front["id"])
        stage = str(front.get("stage") or DEFAULT_STAGE)
        section = _section_of(note, notes)
        lineage = lineage_for(note_id, tenant_id)
        loaded = _loaded_hash(note_id, class_name, stage, section, front_matter_yaml, body)
        claims = _claims_of(front)
        candidate = front.get("rating") == 5
        record = {"id": note_id, "path": note.path, "class": class_name, "stage": stage, "commit": commit, "loadedHash": loaded, **claims,
                  **({FIVE_STAR_CANDIDATE: True} if candidate else {})}
        planned = PlannedNote(
            note.path, note_id, lineage, stage=stage, section=section, claims=record, five_star_candidate=candidate,
            fields=ItemFields(type=ITEM_CLASSES[class_name], slug=slugify(note.stem), section=section, front_matter_yaml=front_matter_yaml, body_markus=body, aliases=[],
                              id=lineage, source_path=note.path, metadata={POD_METADATA_KEY: record}),
        )
        _classify(planned, client, loaded)
        plan.notes.append(planned)
    return plan


def _classify(planned: PlannedNote, client, loaded: str) -> None:
    versions = story_versions(client, planned.lineage)
    if not versions:
        planned.action = CREATED
        return
    current = max((row for row in versions if row.get("versionState") == "current") or versions, key=lambda row: int(row.get("versionNumber") or 0))
    recorded = pod_record(current)
    planned.version = int(current.get("versionNumber") or 1) + 1
    # The newsroom owns a note once a person has changed its record: a version they saved, or a stage they moved. There is no force.
    if current.get("versionCreatedBy") != LOAD_ACTOR or not recorded.get("loadedHash") or current.get("stage") != recorded.get("stage"):
        planned.action = NEWSROOM_OWNED
    elif recorded.get("loadedHash") == loaded:
        planned.action = UNCHANGED
    else:
        planned.action = UPDATED


def apply_plan(plan: Plan, client) -> None:
    """Write every created and updated note. One version for each; an unchanged or newsroom-owned note is not touched."""
    reason = f"Loaded from a pod at commit {plan.commit}"
    for planned in plan.notes:
        assert planned.fields is not None
        if planned.action == CREATED:
            _create(client, planned, reason)
        elif planned.action == UPDATED:
            fields = planned.fields
            save_story_version(
                client, planned.lineage, front_matter_yaml=fields.front_matter_yaml, body_markus=fields.body_markus, actor=LOAD_ACTOR, change_reason=reason,
                stage=planned.stage, item_type=fields.type, overrides={"section": planned.section}, metadata_updates={POD_METADATA_KEY: planned.claims},
            )


def _create(client, planned: PlannedNote, reason: str) -> None:
    fields = planned.fields
    assert fields is not None
    fields.overrides = {"stage": planned.stage, "changeReason": reason, "versionCreatedBy": LOAD_ACTOR}
    save_item(client, fields, actor=LOAD_ACTOR)


def render(plan: Plan, out: TextIO, *, dry_run: bool) -> None:
    kind = "private pod" if plan.private else f"site pod ({SITE_SETTINGS.as_posix()})"
    print(f"pod: {plan.pod}", file=out)
    print(f"commit: {plan.commit}", file=out)
    print(f"kind: {kind}; every note loads as private newsroom data and a load never publishes", file=out)
    for planned in plan.notes:
        verb = planned.action if not dry_run or planned.action in (UNCHANGED, NEWSROOM_OWNED) else f"would be {planned.action}"
        print(f"  {planned.path}: {verb} (stage {planned.stage})", file=out)
        if planned.five_star_candidate:
            print(f"  {planned.path}: rating 5 refused, a pod never grants five stars; listed as a five-star candidate for a person to confirm in the newsroom", file=out)
        if planned.claims.get("reviewedBy") or planned.claims.get("reviewedOn"):
            print(f"  {planned.path}: review recorded as a claim, not verified; a person confirms it in the newsroom", file=out)
    for class_name, count in sorted(plan.skipped_classes.items()):
        print(f"  not loaded by this version: {count} {class_name} note(s)", file=out)
    counts = {action: sum(1 for planned in plan.notes if planned.action == action) for action in (CREATED, UPDATED, UNCHANGED, NEWSROOM_OWNED)}
    summary = ", ".join(f"{count} {action}" for action, count in counts.items())
    print(f"{'dry run, nothing written' if dry_run else 'loaded'}: {summary}; nothing was published", file=out)
    candidates = [planned.path for planned in plan.notes if planned.five_star_candidate]
    if candidates:
        print(f"five-star candidates: {', '.join(candidates)}", file=out)
