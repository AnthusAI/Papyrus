"""``papyrus pod check``: read a pod and report its level and every problem. It reads only; it never writes, mints or repairs anything.

Identity is the note's explicit ``id``. Nothing here derives an identity from a file name or a path: a typed note without an id is a problem,
not a note whose id is guessed.
"""
from __future__ import annotations

import datetime
import difflib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from papyrus_content.guidelines import files as guideline_files

from . import attempts as attempt_lines, context, profile
from .notes import Note, body_hash, name_index, parse, walk
from .profile import Key, RelationType

POD_LEVEL = "(pod)"
GUIDELINES_FOLDER = "guidelines"
HASH_FORM = re.compile(r"^sha256:[0-9a-f]{64}$")
REVIEW_CLAIMS_LINE = ("review keys in a pod are claims, not newsroom review; nothing in a pod satisfies a gate, a required step, "
                      "publishRequiresRating or a five-star rule")
STATES_OF = {"Relation": profile.RELATION_STATES, "Announcement": profile.ANNOUNCEMENT_STATES, "Delivery": profile.DELIVERY_STATES}
LINK_TARGETS = {"section": "Section", "announcement": "Announcement"}    # a link key that must name a note of one class
PAGE_ONLY_KEYS = ("stage", "draft", "format", "redirects", "section")
UTC_TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?Z$")
WIKI_LINK = re.compile(r"^\[\[([^\[\]]*)\]\]$")


@dataclass
class Problem:
    path: str
    message: str


@dataclass
class Report:
    pod: str
    level: int = 0
    notes: int = 0
    typed: int = 0
    history: str = ""
    problems: list[Problem] = field(default_factory=list)


@dataclass
class Link:
    owner: Note         # the note that states it: the source for a key, the Relation note for a Relation note
    source: Note
    relation: str
    target: Note
    via: str            # "the key tagged_with" or "this Relation note"


def check_pod(pod: Path, relation_types_path: str | Path | None = None) -> Report:
    notes = [note for note in walk(pod) if note.path.split("/", 1)[0] != GUIDELINES_FOLDER]
    report = Report(str(pod), notes=len(notes))
    checker = _Checker(pod, notes, report, profile.relation_types(relation_types_path))
    checker.run()
    _check_guidelines(pod / GUIDELINES_FOLDER, report)
    report.problems.sort(key=lambda problem: (problem.path != POD_LEVEL, problem.path))
    return report


def _check_guidelines(folder: Path, report: Report) -> None:
    """The guidelines folder is checked by the guideline checker's own validation, and its files are never read as notes. Only validity is reported."""
    if not folder.exists():
        return
    for problem in guideline_files.load_directory(folder).problems:
        if problem.code in ("empty", "not_a_folder"):
            path = GUIDELINES_FOLDER
        else:
            path = f"{GUIDELINES_FOLDER}/{problem.folder}/{guideline_files.FILE_NAME}"
        message = f"key {problem.key!r} {problem.message}" if problem.key else problem.message
        report.problems.append(Problem(path, message))


class _Checker:
    def __init__(self, pod: Path, notes: list[Note], report: Report, relation_types: list[RelationType]) -> None:
        self.pod = pod
        self.notes = notes
        self.report = report
        self.relations = {entry.key: entry for entry in relation_types}
        self.site_keys: dict[str, Key] = {}
        self.links: list[Link] = []
        self.ends: dict[tuple[str, str], Note] = {}
        self.announcements: dict[str, Note] = {}     # a Delivery note's path -> the Announcement note it belongs to

    def problem(self, path: str, message: str) -> None:
        self.report.problems.append(Problem(path, message))

    def run(self) -> None:
        notes = self.notes
        for note in notes:
            if note.problem:
                self.problem(note.path, note.problem)
        typed = [note for note in notes if note.typed]
        self.report.typed = len(typed)
        root = self.pod / profile.CONTEXT_FILE
        self.report.level = 1 if root.is_file() else 0
        if self.report.level == 0:
            if typed:
                self.problem(POD_LEVEL, f"{len(typed)} note(s) carry a type or an id but the pod has no {profile.CONTEXT_FILE}; run `papyrus pod init` to make it a level 1 pod")
            self.report.history = ""
            return
        self._check_contexts(root)
        by_name = self._index()
        for note in typed:
            self._check_note(note, by_name)
        self._check_duplicate_ids(typed)
        self._check_duplicate_links()
        self._check_records()
        self._check_history()

    # ---- the context files -----------------------------------------------------------------------------------------

    def _check_contexts(self, root: Path) -> None:
        generated = self.pod / profile.PROFILE_CONTEXT_FILE
        if not generated.is_file():
            self.problem(profile.PROFILE_CONTEXT_FILE, "is missing; it is generated by `papyrus pod init`, never written by hand")
        elif (namespace := context.recorded_namespace(generated)) is None:
            self.problem(profile.PROFILE_CONTEXT_FILE, f"does not record a vocabulary namespace as its {profile.NAMESPACE_PREFIX!r} prefix; it is generated by `papyrus pod init`, never edited by hand")
        elif generated.read_text(encoding="utf-8") != context.generate(namespace=namespace):
            self.problem(profile.PROFILE_CONTEXT_FILE, f"is not profile version {profile.PROFILE_VERSION}: it differs from the file Papyrus generates, and a pod never edits it by hand")
        declared, problems = context.read_root(root)
        self.site_keys = declared.site_keys
        for message in problems:
            self.problem(profile.CONTEXT_FILE, message)

    # ---- one typed note -------------------------------------------------------------------------------------------

    def _index(self) -> dict[str, list[Note]]:
        return name_index(self.notes)

    def _check_note(self, note: Note, by_name: dict[str, list[Note]]) -> None:
        front = note.front or {}
        class_name = self._class_of(note, front)
        if "id" not in front:
            self.problem(note.path, "has a type and no id; give it one with `papyrus pod id`. An id is never made from the file name")
        else:
            self._check_id(note, front["id"])
        known = self._keys_for(class_name)
        for name, value in front.items():
            if name in ("id", "type"):
                continue
            if name in self.relations and class_name == "Relation":
                self.problem(note.path, f"key {name!r} is a link between two notes; a Relation note says it with from, relation and to")
                continue
            key = known.get(name)
            if key is None:
                self._unknown_key(note, name, class_name)
                continue
            self._check_value(note, key, value, by_name, class_name)
        self._check_lifecycle(note, front)
        if class_name == "Reference" and "url" not in front:
            self.problem(note.path, "is a Reference and has no url; a Reference is one outside work, found by its address")
        if class_name == "Relation":
            self._check_relation_note(note, front)
        if class_name in profile.NEVER_PAGES:
            self._check_record_note(note, front, class_name)

    def _check_record_note(self, note: Note, front: dict, class_name: str) -> None:
        """An Announcement or a Delivery is a record of what was said and where. It is never a page, so it carries none of the keys that decide a page."""
        for name in PAGE_ONLY_KEYS:
            if name in front:
                self.problem(note.path, f"{_a(class_name)} is never a page, so it has no {name!r}; that key is for a note that is built into a site")
        required = {"Announcement": ("kind", "state"), "Delivery": ("announcement", "channel", "account", "mode", "state")}[class_name]
        missing = [name for name in required if name not in front]
        if missing:
            self.problem(note.path, f"is {_a(class_name)} and has no {', no '.join(missing)}")
        if class_name == "Delivery":
            if not note.body.strip():
                self.problem(note.path, "is a Delivery and has no words; the words, exactly as posted, are the body of the note")
            self._check_state_matches_attempts(note, front)

    def _check_attempts(self, note: Note, value: object) -> None:
        if not isinstance(value, list):
            self.problem(note.path, "key 'attempts' takes a list of lines, one for each attempt")
            return
        for position, line in enumerate(value, 1):
            _, why = attempt_lines.parse(line, position)
            if why:
                self.problem(note.path, f"attempt {position} {why}")

    def _check_state_matches_attempts(self, note: Note, front: dict) -> None:
        """A Delivery that is sent or failed says how its last attempt ended."""
        state = front.get("state")
        wanted = {"sent": "sent", "failed": "refused"}.get(state) if isinstance(state, str) else None
        lines = front.get("attempts", [])
        if not wanted or not isinstance(lines, list):
            return
        parsed = [attempt_lines.parse(line, position)[0] for position, line in enumerate(lines, 1)]
        if None in parsed:
            return    # a line that cannot be read was reported with its key
        if not parsed or parsed[-1].outcome != wanted:
            self.problem(note.path, f"is {state} and its last attempt did not end {wanted}; the state says how the last attempt ended")

    def _check_lifecycle(self, note: Note, front: dict) -> None:
        if "stage" in front and "draft" in front:
            self.problem(note.path, "carries both stage and draft; a note with a stage is built only at published, and a note with no stage is built unless draft: true. Keep one of them")
        stamped = "reviewedBy" in front or "reviewedOn" in front
        stamp = front.get("reviewedHash")
        if stamped and "reviewedHash" not in front:
            self.problem(note.path, "has reviewedBy or reviewedOn and no reviewedHash, so the review cannot be checked against the body")
        if isinstance(stamp, str) and HASH_FORM.match(stamp):
            now = body_hash(note.body)
            if stamp != now:
                self.problem(note.path, f"review is stale: the body no longer matches reviewedHash; it now hashes to {now}")

    def _class_of(self, note: Note, front: dict) -> str | None:
        value = front.get("type")
        if "type" not in front:
            self.problem(note.path, "has an id and no type; add `type: papyrus:Article` (or another class)")
            return None
        if not isinstance(value, str) or not value.startswith(profile.CLASS_PREFIX) or value[len(profile.CLASS_PREFIX):] not in profile.CLASS_KINDS:
            suggestion = ""
            if isinstance(value, str):
                match = difflib.get_close_matches(value.removeprefix(profile.CLASS_PREFIX).capitalize(), list(profile.CLASS_KINDS), n=1)
                if match:
                    suggestion = f"; did you mean papyrus:{match[0]}?"
            self.problem(note.path, f"has the unknown type {value!r}; a type is papyrus: and a class ({', '.join(profile.CLASS_KINDS)}){suggestion}")
            return None
        return value[len(profile.CLASS_PREFIX):]

    def _check_id(self, note: Note, value: object) -> None:
        if not isinstance(value, str) or not value:
            self.problem(note.path, "has an id that is not an address; an id is an https address such as https://example.org/id/<identifier>")
            return
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.netloc or not parts.path.strip("/") or parts.query or parts.fragment or any(c.isspace() for c in value):
            self.problem(note.path, f"has the id {value!r}, which is not an https address with a path; an id looks like https://example.org/id/<identifier>")

    def _keys_for(self, class_name: str | None) -> dict[str, Key]:
        keys = {key.name: key for key in (*profile.PLAIN_KEYS, *profile.LINK_KEYS)}
        for name in self.relations:
            keys[name] = Key(name, f"papyrus:{name}", profile.LINK_LIST)
        if class_name in profile.CLASS_KEYS:
            for key in profile.CLASS_KEYS[class_name]:
                keys[key.name] = key
            if class_name == "Relation":
                for name in self.relations:
                    keys.pop(name, None)
        keys.update(self.site_keys)
        return keys

    def _unknown_key(self, note: Note, name: str, class_name: str | None) -> None:
        owners = [owner for owner, keys in profile.CLASS_KEYS.items() if any(key.name == name for key in keys)]
        if owners:
            names = [_a(owner) + " note" for owner in owners]
            owned = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"
            self.problem(note.path, f"key {name!r} belongs to {owned}, and this note is {_a(class_name) if class_name else 'not one of them'}")
            return
        pool = [*self._keys_for(class_name)]
        match = difflib.get_close_matches(name, pool, n=1)
        hint = f"; did you mean {match[0]!r}?" if match else "; a site declares its own keys in context.jsonld"
        self.problem(note.path, f"has the unknown key {name!r}{hint}")

    # ---- values -------------------------------------------------------------------------------------------------

    def _check_value(self, note: Note, key: Key, value: object, by_name: dict[str, list[Note]], class_name: str | None) -> None:
        name = key.name
        if name == "rating":
            self._check_rating(note, value)
            return
        if isinstance(value, dict) or (isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value)):
            self.problem(note.path, f"key {name!r} has a nested value; the profile has none: make a note of its own for it and link to that note")
            return
        kind = key.kind
        if kind in (profile.LINK, profile.LINK_LIST):
            items = value if isinstance(value, list) else [value]
            if isinstance(value, list) and kind == profile.LINK:
                self.problem(note.path, f"key {name!r} takes one link, not a list")
                return
            for item in items:
                self._check_link(note, key, item, by_name, class_name)
            return
        if kind == profile.STRING:
            if isinstance(value, list):
                self.problem(note.path, f"key {name!r} takes one value, not a list")
            elif not isinstance(value, str) or not value:
                self.problem(note.path, f"key {name!r} takes text")
            elif _wiki(value) is not None:
                self.problem(note.path, f"key {name!r} is a link where text belongs; links go in link keys")
            elif name == "stage" and value not in profile.STAGES:
                match = difflib.get_close_matches(value, profile.STAGES, n=1)
                hint = f"; did you mean {match[0]!r}?" if match else ""
                self.problem(note.path, f"key 'stage' is {value!r}; a stage is one of {', '.join(profile.STAGES)}{hint}")
            elif name == "reviewedHash" and not HASH_FORM.match(value):
                self.problem(note.path, "key 'reviewedHash' is sha256: and 64 hex digits, the hash of the body that was reviewed")
            elif name == "state" and class_name in STATES_OF and value not in STATES_OF[class_name]:
                self.problem(note.path, f"key 'state' is {value!r}; a state is one of {', '.join(STATES_OF[class_name])}")
            elif name == "mode" and value != profile.POD_MODE:
                self.problem(note.path, f"key 'mode' is {value!r}; a pod delivers in {profile.POD_MODE} mode only, because sending automatically needs a connected account, a budget guard and Caducus, which a newsroom has and a pod does not")
            elif name == "releaseAt" and not _utc_time(value):
                self.problem(note.path, "key 'releaseAt' takes a time in UTC written 2026-11-16T14:00Z")
            return
        if kind == profile.TEXT_LIST:
            if name == "attempts":
                self._check_attempts(note, value)
                return
            items = value if isinstance(value, list) else [value]
            for item in items:
                if not isinstance(item, str) or not item:
                    self.problem(note.path, f"key {name!r} takes text, or a list of text")
                    return
                if _wiki(item) is not None:
                    self.problem(note.path, f"key {name!r} is a link where text belongs; links go in link keys")
                    return
            if name == "redirects" and any(not item.startswith("/") for item in items):
                self.problem(note.path, "key 'redirects' lists old addresses, each starting with /")
            return
        if kind == profile.DATE:
            if isinstance(value, datetime.datetime) or not (isinstance(value, datetime.date) or _iso_date(value)):
                self.problem(note.path, f"key {name!r} takes a day written 2026-11-13")
            return
        if kind == profile.BOOLEAN:
            if not isinstance(value, bool):
                self.problem(note.path, f"key {name!r} takes true or false")
            return
        if kind == profile.INTEGER:
            if isinstance(value, bool) or not isinstance(value, int):
                self.problem(note.path, f"key {name!r} takes a whole number")
            return
        if kind == profile.DECIMAL:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self.problem(note.path, f"key {name!r} takes a number")
            return
        if kind == profile.ADDRESS:
            if not isinstance(value, str) or urlsplit(value).scheme not in ("http", "https") or not urlsplit(value).netloc or any(c.isspace() for c in value):
                self.problem(note.path, f"key {name!r} takes an outside address starting with https:// or http://")
            return
        if kind == profile.PREDICATE:
            return    # checked with the rest of a Relation note

    def _check_rating(self, note: Note, value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            self.problem(note.path, "key 'rating' takes a whole number from 1 to 4")
        elif value == 5:
            self.problem(note.path, "key 'rating' is 5, which a pod never grants; this note is a five-star candidate, and a person confirms five stars in the newsroom. Use 4 here")

    def _check_link(self, note: Note, key: Key, item: object, by_name: dict[str, list[Note]], class_name: str | None) -> None:
        target = self._resolve(note, key.name, item, by_name)
        if target is None:
            return
        if key.name in LINK_TARGETS:
            if (target.front or {}).get("type") != f"{profile.CLASS_PREFIX}{LINK_TARGETS[key.name]}":
                self.problem(note.path, f"key {key.name!r} names {target.path}, which is not {_a(LINK_TARGETS[key.name])} note")
            elif key.name == "announcement":
                self.announcements[note.path] = target
            return
        if key.name in self.relations:
            self._record_link(note, note, key.name, target, f"the key {key.name}")
        elif class_name == "Relation" and key.name in ("from", "to"):
            self.ends[(note.path, key.name)] = target

    def _resolve(self, note: Note, key_name: str, item: object, by_name: dict[str, list[Note]]) -> Note | None:
        """The note a front matter link names, or None after reporting why not."""
        text = _wiki(item) if isinstance(item, str) else None
        if text is None:
            self.problem(note.path, f"key {key_name!r} is text where a link belongs; write the note as [[name]]")
            return None
        if "|" in text or "#" in text:
            self.problem(note.path, f"key {key_name!r} has the link [[{text}]], which carries words or a heading; a link in front matter is just [[name]]. Words about a link go in a Relation note")
            return None
        name = text.strip().removesuffix(".md")
        found = by_name.get(name, [])
        exact = [candidate for candidate in found if candidate.path.removesuffix(".md") == name]
        found = exact or found
        if not found:
            self.problem(note.path, f"key {key_name!r} links to [[{text}]], which names no note in the pod")
            return None
        if len(found) > 1:
            paths = ", ".join(candidate.path.removesuffix(".md") for candidate in found)
            self.problem(note.path, f"key {key_name!r} links to [[{text}]], which names {len(found)} notes ({paths}); write the path, as [[{found[0].path.removesuffix('.md')}]]")
            return None
        target = found[0]
        if not target.typed:
            self.problem(note.path, f"key {key_name!r} links to {target.path}, which is not a typed note; give it an id and a type, or link another note")
            return None
        return target

    # ---- links between notes ---------------------------------------------------------------------------------------

    def _kind_of(self, note: Note) -> tuple[str | None, str]:
        value = (note.front or {}).get("type")
        name = value[len(profile.CLASS_PREFIX):] if isinstance(value, str) and value.startswith(profile.CLASS_PREFIX) else ""
        return profile.CLASS_KINDS.get(name), name or "note"

    def _record_link(self, owner: Note, source: Note, relation: str, target: Note, via: str) -> None:
        relation_type = self.relations[relation]
        source_kind, source_name = self._kind_of(source)
        target_kind, target_name = self._kind_of(target)
        forward = source_kind in relation_type.subject_kinds and target_kind in relation_type.object_kinds
        backward = relation_type.symmetric and target_kind in relation_type.subject_kinds and source_kind in relation_type.object_kinds
        if not (forward or backward):
            self.problem(owner.path, f"{relation!r} cannot link {_a(source_name)} to {_a(target_name)} ({via})")
            return
        self.links.append(Link(owner, source, relation, target, via))

    def _check_relation_note(self, note: Note, front: dict) -> None:
        missing = [end for end in ("from", "relation", "to") if end not in front]
        if missing:
            self.problem(note.path, f"is a Relation note and has no {', no '.join(missing)}; a Relation note names both ends and the relation")
            return
        relation = front["relation"]
        name = relation[len(profile.CLASS_PREFIX):] if isinstance(relation, str) and relation.startswith(profile.CLASS_PREFIX) else None
        if name not in self.relations:
            self.problem(note.path, f"key 'relation' is {relation!r}; write papyrus: and one of {', '.join(self.relations)}")
            return
        start, end = self.ends.get((note.path, "from")), self.ends.get((note.path, "to"))
        if start is not None and end is not None:    # an end that did not resolve was reported with its key
            self._record_link(note, start, name, end, f"the Relation note {note.path}")

    def _check_duplicate_links(self) -> None:
        stated: dict[tuple, Link] = {}
        for link in self.links:
            relation_type = self.relations[link.relation]
            ends = (link.source.path, link.target.path)
            if relation_type.symmetric:
                ends = tuple(sorted(ends))
            signature = (link.relation, *ends)
            if signature in stated:
                earlier = stated[signature]
                self.problem(link.owner.path, f"states the link {link.relation!r} between {earlier.source.path} and {earlier.target.path} a second time ({link.via}); it is already stated by {earlier.via}. A link is stated once, as a key or as a note")
            else:
                stated[signature] = link

    # ---- Announcement and Delivery notes ------------------------------------------------------------------------------

    def _check_records(self) -> None:
        announcing = {link.source.path for link in self.links if link.relation == "announces"}
        for note in self.notes:
            if note.front and note.front.get("type") == "papyrus:Announcement" and note.path not in announcing:
                self.problem(note.path, "is an Announcement and announces no Story; an Announcement is about at least one Story, so add announces: [\"[[story]]\"]")
        corrects: dict[str, Note] = {}      # a Delivery's path -> the Delivery it corrects
        successors: dict[str, list[Note]] = {}
        for link in (link for link in self.links if link.relation == "supersedes"):
            new, old = link.source, link.target
            successors.setdefault(old.path, []).append(new)
            corrects[new.path] = old
            same = [self.announcements.get(new.path) is self.announcements.get(old.path)] + [(new.front or {}).get(name) == (old.front or {}).get(name) for name in ("channel", "account")]
            if not all(same):
                self.problem(new.path, f"supersedes {old.path}, which is for another Announcement, channel or account; a correction is for the same Announcement, channel and account as the Delivery it replaces")
            if (old.front or {}).get("state") != "superseded":
                self.problem(old.path, f"is corrected by {new.path} and its state is not superseded; the Delivery that was corrected says so")
        for old_path, news in successors.items():
            if len(news) > 1:
                self.problem(old_path, f"is corrected by {len(news)} Deliveries ({', '.join(new.path for new in news)}); a Delivery has one correction, and the live Delivery is the last of the chain")
        live: dict[tuple, list[Note]] = {}
        for note in self.notes:
            front = note.front or {}
            if front.get("type") == "papyrus:Delivery" and note.path not in successors and note.path in self.announcements:
                key = (self.announcements[note.path].path, front.get("channel"), front.get("account"))
                live.setdefault(key, []).append(note)
        for (announcement, channel, account), group in live.items():
            if len(group) > 1:
                for note in group:
                    self.problem(note.path, f"is one of {len(group)} live Deliveries of {announcement} for {channel} {account} ({', '.join(other.path for other in group if other is not note)}); there is one live Delivery for each Announcement, channel and account, and a second is a correction, so it supersedes the first")
        for note in self.notes:
            front = note.front or {}
            if front.get("type") == "papyrus:Delivery" and front.get("state") == "superseded" and note.path not in successors:
                self.problem(note.path, "is superseded and no Delivery supersedes it; add supersedes to the Delivery that corrects it")
            seen, step = {note.path}, corrects.get(note.path)
            while step is not None:
                if step.path in seen:
                    self.problem(note.path, "is in a ring of corrections: each Delivery in the ring supersedes another")
                    break
                seen.add(step.path)
                step = corrects.get(step.path)

    # ---- identity ---------------------------------------------------------------------------------------------------

    def _check_duplicate_ids(self, typed: list[Note]) -> None:
        owners: dict[str, list[Note]] = {}
        for note in typed:
            value = (note.front or {}).get("id")
            if isinstance(value, str) and value:
                owners.setdefault(value, []).append(note)
        for value, group in owners.items():
            if len(group) > 1:
                for note in group:
                    others = ", ".join(other.path for other in group if other is not note)
                    self.problem(note.path, f"has the same id as {others} ({value}); every note has its own id")

    def _check_history(self) -> None:
        committed = _committed_fronts(self.pod, [note.path for note in self.notes])
        if committed is None:
            self.report.history = "ids are not compared with earlier commits: the pod is not in a git repository with a commit"
            return
        self.report.history = "ids are compared with the last commit, and so are the attempt lines of Delivery notes"
        for note in self.notes:
            earlier = committed.get(note.path)
            if earlier is None:
                continue
            before = earlier.get("id")
            now = (note.front or {}).get("id")
            if isinstance(before, str) and before and before != now:
                self.problem(note.path, f"its id changed since the last commit (was {before}, now {now if now else 'none'}); an id never changes, so restore it with git")
            self._check_attempt_history(note, earlier)

    def _check_attempt_history(self, note: Note, earlier: dict) -> None:
        """The attempts of a Delivery are a log that only grows: a line that was committed is never changed, moved or removed."""
        before = earlier.get("attempts")
        if earlier.get("type") != "papyrus:Delivery" or not isinstance(before, list):
            return
        now = (note.front or {}).get("attempts")
        now = now if isinstance(now, list) else []
        for index, line in enumerate(before):
            if index >= len(now) or now[index] != line:
                found = f"now {now[index]!r}" if index < len(now) else "now missing"
                self.problem(note.path, f"attempt line {index + 1} changed since the last commit (was {line!r}, {found}); an attempt line never changes, so restore it with git and add a new line for what happened since")
                return


def _a(name: str) -> str:
    return f"a {name}" if name[0] not in "AEIOU" else f"an {name}"


def _wiki(value: str) -> str | None:
    match = WIKI_LINK.match(value.strip())
    return match.group(1) if match else None


def _utc_time(value: object) -> bool:
    if not isinstance(value, str) or not UTC_TIME.match(value):
        return False
    try:
        datetime.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _iso_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _committed_fronts(pod: Path, paths: list[str]) -> dict[str, dict] | None:
    """The front matter each note had at the last commit, by path (a note with none committed is left out); None when the pod is not in a git repository with a commit."""
    try:
        for probe in (["--is-inside-work-tree"], ["--verify", "-q", "HEAD"]):
            if subprocess.run(["git", "-C", str(pod), "rev-parse", *probe], capture_output=True, check=False).returncode != 0:
                return None
        batch = subprocess.run(["git", "-C", str(pod), "cat-file", "--batch"], input="".join(f"HEAD:./{path}\n" for path in paths).encode(),
                               capture_output=True, check=False)
    except FileNotFoundError:
        return None
    if batch.returncode != 0:
        return None
    data, position, fronts = batch.stdout, 0, {}
    for path in paths:
        end = data.index(b"\n", position)
        header = data[position:end].split()
        position = end + 1
        if header[-1] == b"missing":
            continue
        size = int(header[2])
        front, _, _ = parse(data[position:position + size].decode("utf-8", errors="replace"))
        position += size + 1
        if front:
            fronts[path] = front
    return fronts
