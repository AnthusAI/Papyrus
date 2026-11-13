"""Editorial checks: Papyrus's editorial policies, checked by Humanus.

Papyrus owns the policies (``EditorialPolicy``), the settings
(``EditorialCheckSettings``) and the editors' decisions (``EditorialFeedback``).
For each request a Humanus policy pack is composed from the stored policies for
the text's language -- the language-neutral policies and the language's own,
publication policies plus the article's section policies, where a section policy
replaces a publication policy with the same key -- and Humanus is called with
that language (``editorial_languages``; PPY-d0132d).

The site's editorial-checks function (core to every Papyrus backend) routes its GraphQL fields through
``handle``; the ``papyrus editorial`` CLI uses the same operations.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import humanus
from humanus.packs import builtin_pack, list_builtin_packs

from .tenant_knowledge_keys import corpus_key_of, is_corpus_id, own_corpora
from .editorial_languages import (
    DEFAULT_LANGUAGES,
    canonical,
    languages_served,
    primary_language,
    site_language,
    site_languages,
    starter_packs_for,
    story_language,
)

LOGGER = logging.getLogger(__name__)

PUBLICATION_SCOPE = "publication"
SETTINGS_ID = "settings"
DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "lanes": {"rules": True, "classifier": True},
    "classifierModel": "jev-latest",
    "rewriteModel": "gpt-6-luna",
    "deadlineSeconds": 20,
    "maxInputTokens": 500_000,
    "maxExamplesPerQuestion": 4,
    "guidance": "",
    "publishWarning": True,
    "checkWhileTyping": True,
    "languages": DEFAULT_LANGUAGES,
}
POLICY_FIELDS = ("policyKey", "scope", "language", "version", "title", "guidance", "severity", "enabled", "detectors", "examples", "rewriteGuidance", "source")


class EditorialStore(Protocol):
    def get_editorial_context(self, section: str | None) -> dict[str, Any]: ...
    def list_policies(self) -> list[dict[str, Any]]: ...
    def get_settings(self) -> dict[str, Any] | None: ...
    def list_feedback(self) -> list[dict[str, Any]]: ...
    def create_policy(self, record: dict[str, Any]) -> None: ...
    def update_policy(self, record: dict[str, Any]) -> None: ...
    def put_settings(self, values: dict[str, Any], *, exists: bool) -> None: ...
    def get_item(self, item_id: str) -> dict[str, Any] | None: ...
    def put_check_run(self, record: dict[str, Any]) -> None: ...
    def get_check_run(self, item_id: str) -> dict[str, Any] | None: ...
    def list_check_runs_by_lineage(self, lineage_id: str, limit: int) -> list[dict[str, Any]]: ...
    # Optional: every current and draft story version of the site, for the cross-story boilerplate check.
    # def list_story_versions(self) -> list[dict[str, Any]]: ...


_DEFAULT = object()


@dataclass
class Services:
    store: EditorialStore
    decision_model: Any = _DEFAULT
    generator: Any = _DEFAULT
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    last_check_request: dict[str, Any] | None = field(default=None, init=False)
    # The site's Prospectus usage sender (papyrus_cost_usage.SiteUsage); None records nothing.
    usage: Any = None

    def checked(self, result: dict[str, Any]) -> dict[str, Any]:
        """Reports the Jev classifier tokens a Humanus check used, then returns the result unchanged."""
        if self.usage is not None:
            self.usage.record_humanus_check(result)
        return result

    def humanus_kwargs(self, name: str) -> dict[str, Any]:
        value = getattr(self, name)
        return {} if value is _DEFAULT else {name: value}


# --- provider keys ------------------------------------------------------------------

PROVIDER_KEYS = ("TYPESAFE_API_KEY", "OPENAI_API_KEY")


def load_provider_keys(
    env: Any = None,
    *,
    read_parameter: Callable[[str], str] | None = None,
) -> None:
    """Put the real provider keys into the environment Humanus reads.

    Amplify hands a Python function each secret() as a placeholder plus an
    AMPLIFY_SSM_ENV_CONFIG map of SSM paths; only Node functions resolve them
    automatically. A key that cannot be resolved is removed, so its lane
    reports "not configured" instead of sending the placeholder to a provider.
    """
    from .amplify_ssm_secrets import _is_amplify_secret_placeholder, _read_ssm_secret

    env = os.environ if env is None else env
    read = read_parameter or _read_ssm_secret
    try:
        config = json.loads(env.get("AMPLIFY_SSM_ENV_CONFIG") or "{}")
    except json.JSONDecodeError:
        config = {}
    for name in PROVIDER_KEYS:
        current = (env.get(name) or "").strip()
        if current and not _is_amplify_secret_placeholder(current):
            continue
        entry = config.get(name) if isinstance(config, dict) else None
        resolved = None
        for path in ((entry or {}).get("path"), (entry or {}).get("sharedPath")):
            if not path:
                continue
            try:
                resolved = (read(path) or "").strip() or None
            except Exception:
                resolved = None
            if resolved:
                break
        if resolved:
            env[name] = resolved
        else:
            env.pop(name, None)


# --- records ----------------------------------------------------------------------


def _json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value) if isinstance(value, str) else value


def _awsjson_document(value: Any) -> Any:
    """The JSON document an AWSJSON field delivers.

    The resolver returns the stringified document, so AppSync hands it over as a JSON string whose content is the
    document: decode until it is no longer a string (at most twice, never looping on a plain string).
    """
    for _ in range(2):
        if not isinstance(value, str):
            break
        value = json.loads(value)
    return value


def policy_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """A stored EditorialPolicy as a Humanus policy (its key becomes the policy id)."""
    policy = {
        "id": record["policyKey"],
        "version": int(record.get("version") or 1),
        "title": record["title"],
        "guidance": record["guidance"],
        "severity": record["severity"],
        "enabled": bool(record.get("enabled", True)),
        "detectors": _json(record.get("detectors"), []),
    }
    examples = _json(record.get("examples"), None)
    if examples:
        policy["examples"] = examples
    if record.get("rewriteGuidance"):
        policy["rewriteGuidance"] = record["rewriteGuidance"]
    return policy


def record_from_policy(policy: dict[str, Any], *, scope: str, language: str, source: str, version: int = 1) -> dict[str, Any]:
    """A Humanus policy as a stored EditorialPolicy written for ``language`` (a tag, or ``*`` for a language-neutral policy)."""
    language = canonical(language)
    return {
        "id": policy_record_id(policy["id"], scope, language),
        "policyKey": policy["id"],
        "scope": scope,
        "language": language,
        "version": version,
        "title": policy["title"],
        "guidance": policy["guidance"],
        "severity": policy["severity"],
        "enabled": policy.get("enabled", True),
        "detectors": policy.get("detectors", []),
        "examples": policy.get("examples"),
        "rewriteGuidance": policy.get("rewriteGuidance"),
        "source": source,
    }


def policy_record_id(policy_key: str, scope: str, language: str) -> str:
    """The id of a new policy record. Two languages may use the same key (``quotation-marks`` in Spanish and in Chinese), so the id names the language.

    Records saved before policies had a language keep their ids; nothing reads a policy by a computed id, only by :func:`policy_identity`."""
    return f"{scope}#{language}#{policy_key}"


class PolicyLanguageMissing(ValueError):
    """A stored policy names no language: it predates PPY-d0132d and the deploy's language backfill has not written it yet."""


def policy_language(record: dict[str, Any]) -> str:
    """The language a stored policy is written for. Never guessed: a record without one is refused until the backfill writes it."""
    language = record.get("language")
    if not language:
        raise PolicyLanguageMissing(
            f"Editorial policy {record.get('id') or record.get('policyKey')} names no language. A deploy writes the language of every older policy; "
            "run `papyrus editorial policies ensure-defaults` to write it now."
        )
    return str(language)


def policy_identity(record: dict[str, Any]) -> tuple[str, str, str]:
    """What makes a policy the same policy: its scope, its language and its key."""
    return (record["scope"], policy_language(record), record["policyKey"])


def settings_from(store: EditorialStore) -> dict[str, Any]:
    stored = store.get_settings()
    values = _json((stored or {}).get("settings"), {})
    settings = {**DEFAULT_SETTINGS, **values}
    settings["lanes"] = {**DEFAULT_SETTINGS["lanes"], **values.get("lanes", {})}
    return settings


class EditorialChecksDisabled(ValueError):
    """The publication turned editorial checks off in its stored settings."""


def running_settings(store: EditorialStore) -> dict[str, Any]:
    """Settings for an operation that runs checks; refuses when the publication turned them off."""
    settings = settings_from(store)
    if not settings["enabled"]:
        raise EditorialChecksDisabled("Editorial checks are turned off for this publication (Administration > Editorial checks).")
    return settings


def compose_pack(records: list[dict[str, Any]], section: str | None, settings: dict[str, Any], language: str) -> dict[str, Any]:
    """The pack for text in ``language``: the language-neutral policies and the language's own (a variant's and its base language's).

    Policies of any other language are left out, so English phrase rules never run on Chinese text and Chinese rules never on English. Where two
    policies share a key, a section's replaces the publication's, and within one scope the more specific language wins (``es-419`` over ``es``
    over ``*``)."""
    served = languages_served(language)
    rank = {tag: index for index, tag in enumerate(served)}
    chosen: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
    for record in records:
        scope = record.get("scope")
        if scope != PUBLICATION_SCOPE and not (section and scope == section):
            continue
        written_for = canonical(policy_language(record))
        if written_for not in rank:
            continue
        order = (0 if scope == PUBLICATION_SCOPE else 1, rank[written_for])
        current = chosen.get(record["policyKey"])
        if current is None or order > current[0]:
            chosen[record["policyKey"]] = (order, record)
    policies = [policy_from_record(chosen[key][1]) for key in sorted(chosen)]
    # The fingerprint covers what is checked and how it is read, not only which policies exist: a policy edited or added without a version
    # bump, the language, the version of Humanus's language pack (how Humanus splits and matches that language's text), or the pack guidance,
    # still changes it. A stored check is reused only under an identical pack version.
    reading = {"language": served[-1], "languagePack": humanus.resolve_language(served[-1]).version}
    fingerprint = hashlib.sha256(json.dumps({**reading, "policies": policies, "guidance": settings.get("guidance") or ""},
                                            sort_keys=True, default=str).encode()).hexdigest()[:12]
    pack: dict[str, Any] = {
        "schemaVersion": 1,
        "packId": "papyrus",
        "version": f"{served[-1]}-{section or PUBLICATION_SCOPE}-{fingerprint}",
        "language": served[-1],
        "policies": policies,
    }
    if settings.get("guidance"):
        pack["guidance"] = settings["guidance"]
    return pack


# --- operations -------------------------------------------------------------------


def skipped_judgments(missing_doctrine: list[str]) -> dict[str, Any]:
    """The classifier lane's status when the publication has no mission (or policy) for its judgments to apply."""
    return {"status": "skipped", "reason": f"this publication has no {' or '.join(missing_doctrine)} yet"}


def requested_language(arguments: dict[str, Any], settings: dict[str, Any]) -> str:
    """The language a request's text is written in, as the site writes it (``es`` means the site's Spanish variant). Required: never assumed."""
    if not arguments.get("language"):
        raise ValueError("Say which language the text is written in (language: en, es-419, zh-Hans ...); it is never assumed.")
    return site_language(str(arguments["language"]), settings)


def check_editorial(arguments: dict[str, Any], services: Services, prepared: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Check text in ``arguments["language"]`` against the pack for its language and section. ``prepared`` is the (settings, pack, context) the caller already built."""
    from .editorial_model_context import editing_pack_and_context
    if prepared is None:
        settings = running_settings(services.store)
        pack, context = editing_pack_and_context(services.store, arguments.get("section"), settings, requested_language(arguments, settings))
    else:
        settings, pack, context = prepared
    # Judgments apply the mission and policy; rule checks do not need them, so they still run (PPY-2c4b56).
    missing_doctrine = context.get("missingPublicationDoctrine") or []
    if missing_doctrine or context.get("missingSectionConfiguration"):
        # Odd editorial context never stops a check; the log names the publication and what was missing, never content.
        LOGGER.warning(
            "Editorial check for %s runs without: %s",
            (context.get("publication") or {}).get("key") or "an unknown publication",
            ", ".join([*(f"publication {kind}" for kind in missing_doctrine), *(["section guidance"] if context.get("missingSectionConfiguration") else [])]),
        )
    lanes = {**settings["lanes"], **(arguments.get("lanes") or {})}  # a caller may override a lane for one call (copy edit turns the classifier off for its rules-only pass)
    skip_judgments = bool(missing_doctrine) and bool(lanes.get("classifier"))
    if skip_judgments:
        lanes["classifier"] = False
    examples = [
        {"policyId": f["policyId"], "detectorId": f["detectorId"], "text": f["text"], "violates": f["decision"] != "dismissed"}
        for f in services.store.list_feedback()
        if f.get("text") and f.get("lane") == "classifier"
    ]
    classifier: dict[str, Any] = {
        "model": settings["classifierModel"],
        "deadlineSeconds": settings["deadlineSeconds"],
        "maxInputTokens": settings["maxInputTokens"],
        "maxExamplesPerQuestion": settings["maxExamplesPerQuestion"],
    }
    if examples:
        classifier["examples"] = examples
    request = {
        "schemaVersion": 1,
        "content": {"format": arguments.get("format") or "markus", "text": arguments["body"], "language": pack["language"]},
        "pack": pack,
        "options": {"lanes": lanes, "classifier": classifier},
    }
    services.last_check_request = request
    result = mark_whole_story_findings(services.checked(humanus.check(request, **services.humanus_kwargs("decision_model"))))
    if skip_judgments:
        result["lanes"]["classifier"] = skipped_judgments(missing_doctrine)
    # No NewsroomSection for the stored value: the section's own mission and policy could not be applied. Say so (PPY-2c4b56).
    missing_sections = context.get("missingSectionConfiguration") or []
    if missing_sections:
        result["lanes"]["section"] = {"status": "skipped", "reason": f"no section configuration for {', '.join(missing_sections)}"}
    return result


WHOLE_STORY_PREFIX = "Applies to the whole story. "


def mark_whole_story_findings(result: dict[str, Any]) -> dict[str, Any]:
    """A document-scope judgment has no passage to quote (Humanus gives it an empty excerpt and one id per detector).

    Say so in the message, so an editor reads "the whole story" instead of an excerpt that is missing by mistake.
    """
    for finding in result.get("findings") or []:
        message = finding.get("message") or ""
        if finding.get("segmentId") == "doc" and not finding.get("excerpt") and not message.startswith(WHOLE_STORY_PREFIX):
            finding["message"] = WHOLE_STORY_PREFIX + message
    return result


def suggest_rewrite(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    from .editorial_model_context import editing_pack
    settings = running_settings(services.store)
    pack = editing_pack(services.store, arguments.get("section"), settings, requested_language(arguments, settings))
    request: dict[str, Any] = {
        "schemaVersion": 1,
        "content": {"format": arguments.get("format") or "markus", "text": arguments["body"], "language": pack["language"]},
        "pack": pack,
        "options": {"model": settings["rewriteModel"], "count": 3},
    }
    if arguments.get("note"):
        request["options"]["instructions"] = arguments["note"]
    finding, selection = _json(arguments.get("finding"), None), _json(arguments.get("selection"), None)
    if finding:
        request["finding"] = finding
    else:
        request["selection"] = selection
    return humanus.suggest(request, **services.humanus_kwargs("generator"))


def draft_questions(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    settings = settings_from(services.store)
    policy: dict[str, Any] = {"title": arguments["title"], "guidance": arguments["guidance"]}
    examples = _json(arguments.get("examples"), None)
    if examples:
        policy["examples"] = examples
    request = {"schemaVersion": 1, "policy": policy, "options": {"model": settings["rewriteModel"]}}
    return humanus.draft_questions(request, **services.humanus_kwargs("generator"))


def try_policy(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    """Try a draft policy on sample text in ``arguments["language"]``, the language the policy is being written for."""
    settings = settings_from(services.store)
    policy = _json(arguments["policy"], {})
    language = requested_language(arguments, settings)
    request = {
        "schemaVersion": 1,
        "content": {"format": arguments.get("format") or "markus", "text": arguments["text"], "language": language},
        "pack": {"schemaVersion": 1, "packId": "papyrus-try", "version": "draft", "language": language, "policies": [policy]},
        "options": {"classifier": {"model": settings["classifierModel"], "deadlineSeconds": settings["deadlineSeconds"]}},
    }
    return mark_whole_story_findings(services.checked(humanus.check(request, **services.humanus_kwargs("decision_model"))))


def import_starter_pack(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    """Add a starter pack's policies the site does not have yet, each written for the pack's language."""
    name = arguments["name"]
    pack = builtin_pack(name)
    existing = {policy_identity(r) for r in services.store.list_policies()}
    created = skipped = 0
    for policy in pack["policies"]:
        record = record_from_policy(policy, scope=PUBLICATION_SCOPE, language=pack["language"], source=f"starter:{name}")
        if policy_identity(record) in existing:
            skipped += 1
            continue
        services.store.create_policy(record)
        created += 1
    return {"created": created, "skipped": skipped}


def list_starter_packs(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    """The starter packs the installed Humanus ships, read at run time so new packs appear without a Papyrus change."""
    defaults = {name for language in site_languages(settings_from(services.store))["enabled"] for name in starter_packs_for(language)}
    imported: dict[str, int] = {}
    for record in services.store.list_policies():
        source = str(record.get("source") or "")
        if source.startswith("starter:"):
            imported[source.removeprefix("starter:")] = imported.get(source.removeprefix("starter:"), 0) + 1
    packs = []
    for name in list_builtin_packs():
        pack = builtin_pack(name)
        policies = pack.get("policies") or []
        packs.append({
            "name": name,
            "title": pack.get("title") or name,
            "version": pack.get("version"),
            "language": pack.get("language"),
            "guidance": pack.get("guidance"),
            "policyCount": len(policies),
            "importedCount": imported.get(name, 0),
            "isDefault": name in defaults,
            "policies": [
                {
                    "id": policy["id"],
                    "title": policy.get("title"),
                    "severity": policy.get("severity"),
                    "tags": policy.get("tags") or [],
                    "lanes": sorted({detector.get("lane") for detector in policy.get("detectors") or [] if detector.get("lane")}),
                }
                for policy in policies
            ],
        })
    return {"humanusVersion": getattr(humanus, "__version__", None), "packs": packs}


def default_starter_packs(settings: dict[str, Any]) -> tuple[str, ...]:
    """The starter packs of every language the site writes in (``editorial_languages.DEFAULT_STARTER_PACKS``)."""
    return tuple(dict.fromkeys(name for language in site_languages(settings)["enabled"] for name in starter_packs_for(language)))


def older_policy_language(record: dict[str, Any], primary: str) -> str:
    """The language a policy saved before policies had one was written for: its starter pack's language, else the site's primary language.

    Before PPY-d0132d every site wrote in one language and every policy was written in it; only a starter pack names its own."""
    source = str(record.get("source") or "")
    if source.startswith("starter:") and source.removeprefix("starter:") in list_builtin_packs():
        return canonical(builtin_pack(source.removeprefix("starter:"))["language"])
    return primary


def ensure_policy_languages(store: EditorialStore) -> int:
    """Write the language of every policy saved before policies had one (the deploy runs this once per site; later runs find nothing).

    The language is written into the record, so no reader ever guesses it. The record keeps its id and version: what it checks is unchanged."""
    primary = primary_language(settings_from(store))
    written = 0
    for record in store.list_policies():
        if record.get("language"):
            continue
        store.update_policy({**record, "language": older_policy_language(record, primary)})
        written += 1
    return written


def ensure_default_policies(store: EditorialStore, packs: tuple[str, ...] | None = None) -> dict[str, Any]:
    """A publication starts with working policies in every language it writes: each default starter pack is imported once.

    ``packs`` defaults to the starter packs of the site's enabled languages, so enabling Chinese or Spanish in the settings brings that
    language's starter rules on the next deploy (or ``papyrus editorial policies ensure-defaults``). The packs applied are recorded in the stored
    settings (``defaultStarterPacks``), so a policy an admin later edits, disables or deletes is never added back. Policies that already exist with
    the same scope, language and key are left alone. Older policies without a language get theirs written first.
    """
    languages_written = ensure_policy_languages(store)
    stored = store.get_settings()
    values = _json((stored or {}).get("settings"), {})
    if packs is None:
        packs = default_starter_packs({**DEFAULT_SETTINGS, **values})
    applied = list(values.get("defaultStarterPacks") or [])
    results: dict[str, Any] = {}
    for name in packs:
        if name in applied:
            results[name] = {"created": 0, "skipped": 0, "alreadyApplied": True}
            continue
        results[name] = import_starter_pack({"name": name}, Services(store=store))
        applied.append(name)
    if applied != list(values.get("defaultStarterPacks") or []):
        store.put_settings({**values, "defaultStarterPacks": applied}, exists=stored is not None)
    return {"packs": results, "defaultStarterPacks": applied, "policyLanguagesWritten": languages_written}


FINDING_SUMMARY_FIELDS = ("id", "policyId", "severity", "status", "message", "excerpt", "probability")


def check_run_record(item: dict[str, Any], result: dict[str, Any], checked_at: datetime) -> dict[str, Any]:
    """The stored outcome of checking one saved version: counts, a compact list of findings and lane status."""
    findings = result.get("findings") or []
    return {
        "id": item["id"],
        "itemId": item["id"],
        "lineageId": item.get("lineageId") or item["id"],
        "versionNumber": int(item.get("versionNumber") or 1),
        "section": item.get("section"),
        "contentHash": item.get("contentHash"),
        "packVersion": (result.get("pack") or {}).get("version") or result.get("packVersion"),
        "violations": sum(1 for finding in findings if finding.get("status") == "violation"),
        "reviews": sum(1 for finding in findings if finding.get("status") == "review"),
        "findings": [{key: finding.get(key) for key in FINDING_SUMMARY_FIELDS if finding.get(key) is not None} for finding in findings],
        "lanes": result.get("lanes"),
        "checkedAt": checked_at.isoformat().replace("+00:00", "Z"),
    }


CHECK_SUMMARY_KEYS = ("itemId", "lineageId", "versionNumber", "violations", "reviews", "packVersion", "checkedAt", "lanes")
# A stored lane that did not finish is not a result worth keeping: the next check of the same text runs again.
FINISHED_LANE_STATUSES = ("ran", "disabled", "skipped")
# What a lane that the settings turn on must have done for a stored check to stand in for a new one.
COVERING_LANE_STATUSES = ("ran", "skipped")
PRIOR_RUNS_CONSIDERED = 3


def _finished(run: dict[str, Any]) -> bool:
    lanes = _awsjson_document(run.get("lanes")) or {}
    return all((lane or {}).get("status") in FINISHED_LANE_STATUSES for lane in lanes.values() if isinstance(lane, dict))


def _covers_enabled_lanes(run: dict[str, Any], enabled: dict[str, Any]) -> bool:
    """A lane the settings turn on must have run (or been skipped for want of doctrine) in the stored check.

    A check made with the judgment lane off (a rules-only copy edit, say) must not stand in for one with it on.
    """
    lanes = _awsjson_document(run.get("lanes")) or {}
    return all(((lanes.get(name) or {}).get("status") in COVERING_LANE_STATUSES) for name, on in enabled.items() if on and name in ("rules", "classifier"))


def lanes_not_run(lanes: Any) -> list[str]:
    """Plain statements for each lane that did not run, so a result without judgments never reads as passing them."""
    notes = []
    for name, lane in (_awsjson_document(lanes) or {}).items():
        if not isinstance(lane, dict) or name not in ("rules", "classifier", "section") or lane.get("status") == "ran":
            continue
        label = {"classifier": "judgment questions", "rules": "rule checks", "section": "section configuration"}[name]
        reason = f": {lane['reason']}" if lane.get("reason") else ""
        notes.append(f"{label} did not run ({lane.get('status')}{reason})")
    return notes


def reusable_check_run(item: dict[str, Any], services: Services, *, pack_version: str, lanes: dict[str, Any]) -> dict[str, Any] | None:
    """A finished stored check of identical content under identical policies: this version's own, or a recent earlier one.

    The key is the version's content hash (front matter and body), its section, and the pack version, whose fingerprint
    covers the full text of the policies that apply (and the context they were checked with). Identical content under
    identical policies is never sent to the provider again; a policy that was added or changed makes the stored check
    stale, so the next check of this version runs. A check stored before the pack version held that fingerprint never
    matches. A check whose enabled lanes did not all run is not reused either.
    """
    content_hash = item.get("contentHash")
    if not content_hash:
        return None
    candidates = [services.store.get_check_run(item["id"])]
    lineage_id = item.get("lineageId") or item["id"]
    candidates += services.store.list_check_runs_by_lineage(lineage_id, PRIOR_RUNS_CONSIDERED)
    for run in candidates:
        if (run and run.get("contentHash") == content_hash and (run.get("section") or None) == (item.get("section") or None)
                and run.get("packVersion") == pack_version and _finished(run) and _covers_enabled_lanes(run, lanes)):
            return run
    return None


def with_cross_story_findings(item: dict[str, Any], findings: list[dict[str, Any]], services: Services, segments: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """``findings`` with this version's cross-story boilerplate findings, computed now against the site's other stories.

    These depend on the other stories, not only on this version's content, so they are never reused from an earlier
    check. A store without ``list_story_versions`` (a policy file) has no corpus and adds none.
    """
    from . import cross_story_boilerplate as boilerplate

    kept = [finding for finding in findings if finding.get("policyId") != boilerplate.POLICY_ID]
    list_versions = getattr(services.store, "list_story_versions", None)
    if list_versions is None:
        return kept
    lineage_id = item.get("lineageId") or item["id"]
    others = [story for story in boilerplate.latest_stories(list_versions()) if story.lineage_id != lineage_id]
    if not others:
        return kept
    index = boilerplate.ShingleIndex(others)
    return kept + boilerplate.cross_story_findings(item.get("bodyMarkus") or "", lineage_id, index, segments)


def _counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    return {"violations": sum(1 for f in findings if f.get("status") == "violation"), "reviews": sum(1 for f in findings if f.get("status") == "review")}


def check_item_version(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    """Check one saved version of a story against its section's pack and store the result with the version.

    Every save path (the article editor, ``stories save-version``, imports, copywriting) calls this, so drafts written
    by people and by agents are copy-edited the same way. Turned-off checks are a skip, not an error. A version whose
    content, section and policies were already checked is not checked again: its stored result is kept or copied to it,
    and the answer says ``reused`` with the time of the check it came from, so a reused result never reads as a fresh one.
    Cross-story boilerplate findings are the exception: they are recomputed now against the site's other stories.
    """
    from .editorial_model_context import editing_pack_and_context
    item = services.store.get_item(arguments["itemId"])
    if item is None:
        raise ValueError(f"No item version {arguments['itemId']}.")
    try:
        settings = running_settings(services.store)
    except EditorialChecksDisabled:
        return {"itemId": item["id"], "skipped": "disabled"}
    pack, context = editing_pack_and_context(services.store, item.get("section"), settings, story_language(item, settings))
    reusable = reusable_check_run(item, services, pack_version=pack["version"], lanes=settings["lanes"])
    if reusable is not None:
        stored = _awsjson_document(reusable.get("findings")) or []
        findings = with_cross_story_findings(item, stored, services)
        counts = _counts(findings)
        lanes = _awsjson_document(reusable.get("lanes"))
        if reusable.get("id") != item["id"] or findings != stored:
            services.store.put_check_run({
                **{key: reusable.get(key) for key in ("section", "contentHash", "packVersion", "checkedAt")},
                **counts,
                "id": item["id"], "itemId": item["id"], "lineageId": item.get("lineageId") or item["id"],
                "versionNumber": int(item.get("versionNumber") or 1),
                "findings": [{key: finding.get(key) for key in FINDING_SUMMARY_FIELDS if finding.get(key) is not None} for finding in findings],
                "lanes": lanes,
            })
        return {**{key: reusable.get(key) for key in CHECK_SUMMARY_KEYS}, **counts, "itemId": item["id"], "lanes": lanes,
                "skipped": "unchanged", "reused": True, "reusedFrom": reusable.get("itemId") or reusable.get("id")}
    result = check_editorial({"body": item.get("bodyMarkus") or "", "format": "markus", "section": item.get("section"), "language": pack["language"]},
                             services, prepared=(settings, pack, context))
    result = {**result, "findings": with_cross_story_findings(item, result.get("findings") or [], services, result.get("segments"))}
    record = check_run_record(item, result, services.now())
    if services.last_check_request:
        record["packVersion"] = services.last_check_request["pack"].get("version")
    services.store.put_check_run(record)
    return {key: record[key] for key in CHECK_SUMMARY_KEYS if key != "itemId"} | {"itemId": record["itemId"], "reused": False}


def recalibrate(arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    labels = [
        {"policyId": f["policyId"], "detectorId": f["detectorId"], "probability": float(f["probability"]), "violates": f["decision"] != "dismissed"}
        for f in services.store.list_feedback()
        if f.get("lane") == "classifier" and f.get("probability") is not None
    ]
    if not labels:
        return {"updated": 0, "detectors": []}
    calibration = humanus.calibrate({"schemaVersion": 1, "labels": labels})
    by_key = {(d["policyId"], d["detectorId"]): d for d in calibration["detectors"] if "calibration" in d}
    updated = 0
    for record in services.store.list_policies():
        detectors = _json(record.get("detectors"), [])
        changed = False
        for detector in detectors:
            fit = by_key.get((record["policyKey"], detector.get("id")))
            if fit and detector.get("lane") == "classifier" and detector.get("calibration") != fit["calibration"]:
                detector["calibration"] = fit["calibration"]
                changed = True
        if changed:
            services.store.update_policy({**record, "detectors": detectors, "version": int(record.get("version") or 1) + 1})
            updated += 1
    return {"updated": updated, "detectors": calibration["detectors"]}


OPERATIONS: dict[str, Callable[[dict[str, Any], Services], dict[str, Any]]] = {
    "checkEditorial": check_editorial,
    "suggestEditorialRewrite": suggest_rewrite,
    "draftEditorialQuestions": draft_questions,
    "tryEditorialPolicy": try_policy,
    "importEditorialStarterPack": import_starter_pack,
    "recalibrateEditorialPolicies": recalibrate,
    "checkItemVersion": check_item_version,
    "listEditorialStarterPacks": list_starter_packs,
}


def event_field_name(event: dict[str, Any]) -> str:
    """The GraphQL field an AppSync invocation is for.

    Amplify's Lambda data source payload carries ``fieldName`` at the top level; a direct resolver
    carries it under ``info``. Accept both so the function works however AppSync wires it.
    """
    info = event.get("info")
    name = (info.get("fieldName") if isinstance(info, dict) else None) or event.get("fieldName")
    if not name:
        raise ValueError("The invocation names no GraphQL field")
    return str(name)


def handle(field_name: str, arguments: dict[str, Any], services: Services) -> dict[str, Any]:
    operation = OPERATIONS.get(field_name)
    if operation is None:
        raise ValueError(f"Unknown editorial-checks operation {field_name}")
    try:
        return operation(arguments, services)
    except (humanus.ContractValidationError, humanus.UnsupportedLanguageError) as error:
        raise ValueError(str(error)) from error


# --- GraphQL store ----------------------------------------------------------------

_POLICY_SELECTION = "id policyKey scope language version title guidance severity enabled detectors examples rewriteGuidance source"
LIST_POLICIES = f"query ListEditorialPolicies($nextToken: String) {{ listEditorialPolicies(limit: 500, nextToken: $nextToken) {{ items {{ {_POLICY_SELECTION} }} nextToken }} }}"
GET_SETTINGS = "query GetEditorialCheckSettings($id: ID!) { getEditorialCheckSettings(id: $id) { id settings } }"
LIST_FEEDBACK = "query ListEditorialFeedbacks($nextToken: String) { listEditorialFeedbacks(limit: 1000, nextToken: $nextToken) { items { policyId detectorId lane probability decision text } nextToken } }"
CREATE_POLICY = "mutation CreateEditorialPolicy($input: CreateEditorialPolicyInput!) { createEditorialPolicy(input: $input) { id } }"
UPDATE_POLICY = "mutation UpdateEditorialPolicy($input: UpdateEditorialPolicyInput!) { updateEditorialPolicy(input: $input) { id } }"
GET_ITEM = "query GetItemForEditorialCheck($id: ID!) { getItem(id: $id) { id lineageId versionNumber section contentHash bodyMarkus } }"
LIST_STORY_VERSIONS = "query ListStoryVersionsForEditorialCheck($versionState: String!, $nextToken: String) { listItemsByVersionStateAndUpdatedAt(versionState: $versionState, limit: 200, nextToken: $nextToken) { items { id lineageId versionNumber versionState type stage slug bodyMarkus } nextToken } }"
GET_CHECK_RUN = "query GetEditorialCheckRun($id: ID!) { getEditorialCheckRun(id: $id) { id } }"
_CHECK_RUN_SELECTION = "id itemId lineageId versionNumber section contentHash packVersion violations reviews findings lanes checkedAt"
GET_CHECK_RUN_RECORD = f"query GetEditorialCheckRunRecord($id: ID!) {{ getEditorialCheckRun(id: $id) {{ {_CHECK_RUN_SELECTION} }} }}"
LIST_CHECK_RUNS_BY_LINEAGE = (
    "query ListEditorialCheckRunsByLineage($lineageId: String!, $limit: Int) { "
    f"listEditorialCheckRunsByLineage(lineageId: $lineageId, sortDirection: DESC, limit: $limit) {{ items {{ {_CHECK_RUN_SELECTION} }} }} }}"
)
CREATE_CHECK_RUN = "mutation CreateEditorialCheckRun($input: CreateEditorialCheckRunInput!) { createEditorialCheckRun(input: $input) { id } }"
UPDATE_CHECK_RUN = "mutation UpdateEditorialCheckRun($input: UpdateEditorialCheckRunInput!) { updateEditorialCheckRun(input: $input) { id } }"
CREATE_SETTINGS = "mutation CreateEditorialCheckSettings($input: CreateEditorialCheckSettingsInput!) { createEditorialCheckSettings(input: $input) { id } }"
UPDATE_SETTINGS = "mutation UpdateEditorialCheckSettings($input: UpdateEditorialCheckSettingsInput!) { updateEditorialCheckSettings(input: $input) { id } }"


class GraphQLEditorialStore:
    """The editorial models through AppSync, signed the Papyrus way (IAM for functions and the CLI)."""

    def __init__(self, execute: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
                 tenant_id: str | None = None) -> None:
        if execute is None:
            from .graphql_http import execute_graphql

            execute = execute_graphql
        self._execute = execute
        self._tenant_id = tenant_id   # the calling client's tenant; without one, the environment's or the signed-in site's

    def _list(self, query: str, field_name: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token = None
        while True:
            page = self._execute(query, {"nextToken": token})[field_name]
            items.extend(page["items"])
            token = page.get("nextToken")
            if not token:
                return items

    def list_policies(self) -> list[dict[str, Any]]:
        return self._list(LIST_POLICIES, "listEditorialPolicies")

    def publication_key(self) -> str:
        """The key of the site's one verified canonical publication."""
        query = '''query CanonicalEditorialPublication($nextToken: String) {
          listKnowledgeCorporaByRoleAndName(role: "canonical", limit: 100, nextToken: $nextToken) {
            items { id name role } nextToken
          }
        }'''
        rows = own_corpora(self._list(query, 'listKnowledgeCorporaByRoleAndName'))
        if (len(rows) != 1 or rows[0].get('role') != 'canonical'
                or not is_corpus_id(str(rows[0].get('id', '')))):
            raise ValueError('Exactly one verified publication is required for editorial context')
        return corpus_key_of(rows[0]['id'])

    def get_editorial_context(self, section: str | None) -> dict[str, Any]:
        from .editorial_model_context import checked_context
        from .tenancy import configured_tenant_id
        publication = self.publication_key()
        # Optional doctrine: a publication without a mission still gets its rule checks (PPY-2c4b56).
        result = self._execute('''query EffectiveEditorialContext($publicationKey: String!, $sectionId: ID) {
          getEditorialContext(publicationKey: $publicationKey, sectionId: $sectionId, optionalPublicationDoctrine: true)
        }''', {'publicationKey': publication, 'sectionId': section})['getEditorialContext']
        pack = checked_context(_awsjson_document(result), publication=publication, section=section)
        if (pack['publication'].get('tenantId') or None) != (self._tenant_id or configured_tenant_id() or None):
            raise ValueError('Editorial context tenant mismatch')
        return pack

    def get_settings(self) -> dict[str, Any] | None:
        return self._execute(GET_SETTINGS, {"id": SETTINGS_ID})["getEditorialCheckSettings"]

    def list_feedback(self) -> list[dict[str, Any]]:
        return self._list(LIST_FEEDBACK, "listEditorialFeedbacks")

    def create_policy(self, record: dict[str, Any]) -> None:
        self._execute(CREATE_POLICY, {"input": policy_input(record)})

    def update_policy(self, record: dict[str, Any]) -> None:
        self._execute(UPDATE_POLICY, {"input": policy_input(record)})

    def put_settings(self, values: dict[str, Any], *, exists: bool) -> None:
        self._execute(UPDATE_SETTINGS if exists else CREATE_SETTINGS, {"input": {"id": SETTINGS_ID, "settings": json.dumps(values)}})

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        return self._execute(GET_ITEM, {"id": item_id})["getItem"]

    def list_story_versions(self) -> list[dict[str, Any]]:
        """The site's current and draft item versions, with their bodies, for the cross-story boilerplate check."""
        rows: list[dict[str, Any]] = []
        for state in ("current", "draft"):
            token = None
            while True:
                page = self._execute(LIST_STORY_VERSIONS, {"versionState": state, "nextToken": token})["listItemsByVersionStateAndUpdatedAt"]
                rows.extend(row for row in page["items"] if row.get("type") != "sub-task")   # a checklist step has no text to compare
                token = page.get("nextToken")
                if not token:
                    break
        return rows

    def get_check_run(self, item_id: str) -> dict[str, Any] | None:
        return self._execute(GET_CHECK_RUN_RECORD, {"id": item_id})["getEditorialCheckRun"]

    def list_check_runs_by_lineage(self, lineage_id: str, limit: int) -> list[dict[str, Any]]:
        return self._execute(LIST_CHECK_RUNS_BY_LINEAGE, {"lineageId": lineage_id, "limit": limit})["listEditorialCheckRunsByLineage"]["items"]

    def put_check_run(self, record: dict[str, Any]) -> None:
        exists = self._execute(GET_CHECK_RUN, {"id": record["id"]})["getEditorialCheckRun"] is not None
        payload = {**record, "findings": json.dumps(record["findings"]), "lanes": json.dumps(record["lanes"]) if record.get("lanes") is not None else None}
        self._execute(UPDATE_CHECK_RUN if exists else CREATE_CHECK_RUN, {"input": payload})


def policy_input(record: dict[str, Any]) -> dict[str, Any]:
    """A policy record as GraphQL input: JSON fields as strings."""
    payload = {"id": record["id"], **{key: record.get(key) for key in POLICY_FIELDS}}
    for key in ("detectors", "examples"):
        if payload[key] is not None and not isinstance(payload[key], str):
            payload[key] = json.dumps(payload[key])
    return payload
