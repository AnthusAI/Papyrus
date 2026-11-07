from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from papyrus_newsroom import reference_actions as newsroom_reference_actions

from .assignments import apply_assignment_action
from .env import PAPYRUS_ROOT
from .graphql_authoring import create_authoring_client
from .ids import hash_short, knowledge_corpus_id
from .model_defaults import (
    DEFAULT_REFERENCE_FILTER_MODEL,
    DEFAULT_REFERENCE_SUMMARY_MODEL,
)
from .newsroom_summary import (
    semantic_relation_count_delta,
    update_newsroom_summary_after_assignment_creates,
    update_newsroom_summary_after_extracted_text_attachments,
    update_newsroom_summary_delta,
)
from .options import (
    normalize_non_negative_integer,
    normalize_positive_integer,
    normalize_string,
    parse_boolean_option,
    parse_options,
    parse_repeated_option,
    resolve_mutation_apply,
)
from .records import apply_record_changes, build_record_changes, build_record_changes_targeted_by_id
from .reference_assignments import (
    build_reference_identifier_backfill_assignment_plan,
    build_text_extraction_assignment_records,
    doi_backfill_compatibility_flags,
    execute_reference_text_extraction_assignment,
    normalize_identifier_types,
    timestamp_for_path,
)
from .reference_discovery import run_citation_led_discovery
from .assignment_executors import execute_assignment_by_type
from .reference_attachments import build_extracted_text_attachment_plans
from .reference_citation_resolution import build_reference_citation_resolution_records
from .reference_exports import build_reference_analysis_manifest, build_reference_scope_training_export
from .reference_reads import announce_full_read, attachments_for_references, reference_by_token, subject_relations_for_references, targeted_scope
from .reference_url_text import (
    build_reference_citation_count_records,
    run_reference_identifier_dedupe,
    run_reference_extracted_text_filtering,
    run_reference_source_find,
    run_reference_url_text_extraction,
)
from .reference_metadata_generation import run_reference_metadata_generation_from_extracted_text
from .reference_labels import (
    apply_label_relation,
    apply_unlabel_relation,
    build_accept_authoritative_label_from_prediction,
    build_classification_prediction_rows,
    build_label_rows,
    build_manual_authoritative_label_relation,
    find_current_authoritative_label,
    print_reference_label_plan,
    resolve_category_any,
    resolve_category_in_set,
    resolve_reference_any,
    resolve_reference_for_label,
)
from .reference_policy import normalize_reference_rejection_reason_code
from .reference_stars import MAXIMUM_STARS, MINIMUM_STARS, validated_stars
from .source_readiness import build_extraction_index
from .steering import load_steering_config, require_corpus_config, require_steering_config


def _section_option(options: dict[str, Any]) -> str:
    section = options.get("section") or options.get("section-id")
    if section is True:
        raise ValueError("--section requires a newsroom section id.")
    return str(section or "")


def references_review_curation(flags: list[str]) -> None:
    options = parse_options(flags)
    reference_id = options.get("reference") or options.get("reference-id")
    if not reference_id:
        raise ValueError("references review-curation requires --reference <id>.")
    if not options.get("action"):
        raise ValueError("references review-curation requires --action accept|reject|reopen|archive.")
    note = str(options.get("note") or "")
    # Words are a reason: a reject with --note needs no --reason-code, because the
    # curation Lambda reads those words for the code they name.
    reason_code = normalize_reference_rejection_reason_code(
        options.get("reason-code") or options.get("reasonCode"),
        required=str(options.get("action")).lower() == "reject" and not note.strip(),
    )
    client, _ = create_authoring_client()
    review = newsroom_reference_actions.review_reference_curation(
        client.graphql,
        reference_id=str(reference_id),
        action=str(options["action"]),
        note=note,
        actor_label=str(options.get("actor") or "Papyrus content CLI"),
        reason_code=reason_code or "",
        section_id=_section_option(options),
    )
    print(
        f"references\treview-curation\t{review.get('referenceId')}\t{review.get('action')}\t"
        f"{review.get('status')}\t{review.get('reasonCode') or ''}"
    )


def _uses_delegation(options: dict[str, Any]) -> bool:
    """Delegation is optional: only a command that names a delegation (or the person it was granted by) takes that route."""
    return any(options.get(name) is not None for name in ("delegation-file", "delegation-token", "on-behalf-of"))


def _agent_option(options: dict[str, Any]) -> str:
    agent = options.get("agent")
    return "" if agent is None or agent is True else str(agent).strip()


def references_record_on_behalf_of(flags: list[str], *, action: str, graphql: Any = None) -> None:
    """papyrus references approve|reject --reference <id> [--agent <your name>] [--reason-code ...] [--note ...] [--section <newsroom section id>, accept only] [--dry-run]

    Accepts or rejects as the person signed in to this CLI (papyrus login): their decision, recorded as theirs, with a plain note that it came
    through the CLI (and --agent's name). No delegation, code or approval is needed. A rejection needs a reason: --note or --reason-code.

    Optional, for anyone who uses delegations: with --delegation-file <path> (or --delegation-token, or --on-behalf-of) it records a decision
    relayed under that delegation instead, which also needs --on-behalf-of <person's sign-in email>, --agent and --instruction "<the person's words>".
    """
    options = parse_options(flags)
    if options.get("help"):
        print(references_record_on_behalf_of.__doc__)
        return
    if not _uses_delegation(options):
        _record_as_signed_in_person(options, action=action, graphql=graphql)
        return
    reference_id, on_behalf_of, agent_label, token = _relay_arguments(options, f"references {action}")
    # "approve" is the word the person says; the curation action it records is "accept".
    action = {"approve": "accept"}.get(action, action)
    note = str(options.get("note") or "")
    reason_code = normalize_reference_rejection_reason_code(
        options.get("reason-code") or options.get("reasonCode"),
        required=action == "reject" and not note.strip())
    client, _ = create_authoring_client()
    recorded = newsroom_reference_actions.record_delegated_curation(
        client.graphql, reference_id=str(reference_id), action=action, delegation_token=str(token),
        agent_label=str(agent_label), on_behalf_of=str(on_behalf_of),
        instruction=str(options["instruction"]), note=note,
        reason_code=reason_code or "", section_id=_section_option(options))
    print(f"references\t{action}\t{recorded.get('referenceId')}\t{recorded.get('status')}\t"
          f"{recorded.get('reasonCode') or ''}\ton behalf of {on_behalf_of} via {agent_label}")


def _record_as_signed_in_person(options: dict[str, Any], *, action: str, graphql: Any = None) -> None:
    reference_id = options.get("reference") or options.get("reference-id")
    if not reference_id or reference_id is True:
        raise ValueError(f"references {action} requires --reference <id>.")
    apply = resolve_mutation_apply(options, f"references {action}")
    action = {"approve": "accept"}.get(action, action)
    note = "" if options.get("note") is True else str(options.get("note") or "")
    reason_code = normalize_reference_rejection_reason_code(
        options.get("reason-code") or options.get("reasonCode"),
        required=action == "reject" and not note.strip())
    section_id = _section_option(options)
    agent_label = _agent_option(options)
    via = f"as the signed-in person via {agent_label}" if agent_label else "as the signed-in person"
    if not apply:
        print(f"references\t{action}\t{reference_id}\t{via}\tdry-run: nothing sent")
        return
    if graphql is None:
        graphql = create_authoring_client()[0].graphql
    recorded = newsroom_reference_actions.review_reference_curation_as_signed_in_person(
        graphql, reference_id=str(reference_id), action=action, note=note, reason_code=reason_code or "",
        section_id=section_id, agent_label=agent_label)
    print(f"references\t{action}\t{recorded.get('referenceId')}\t{recorded.get('status')}\t{recorded.get('reasonCode') or ''}\t{via}")


def _relay_arguments(options: dict[str, Any], label: str) -> tuple[str, str, str, str]:
    """The reference, the person, the agent and the delegation token every relayed decision names, or a message saying which are missing."""
    reference_id = options.get("reference") or options.get("reference-id")
    on_behalf_of = options.get("on-behalf-of")
    agent_label = options.get("agent")
    delegation_file = options.get("delegation-file")
    token = (
        options.get("delegation-token")
        or (newsroom_reference_actions.read_delegation_token_file(str(delegation_file)) if delegation_file and delegation_file is not True else None)
        or os.environ.get("PAPYRUS_DELEGATION_TOKEN")
    )
    missing = [name for name, value in (("--reference", reference_id), ("--on-behalf-of", on_behalf_of),
                                        ("--agent", agent_label), ("--instruction", options.get("instruction")), ("--delegation-file, --delegation-token or PAPYRUS_DELEGATION_TOKEN", token))
               if not value or value is True]
    if missing:
        raise ValueError(f"{label} requires {', '.join(missing)}.")
    return str(reference_id), str(on_behalf_of), str(agent_label), str(token)


def _stars_option(value: Any) -> int | None:
    """``--stars 1..5`` or ``--stars clear``, with the ``setReferenceStars`` rules (``reference_stars``)."""
    if value is None or value is True:
        raise ValueError("references set-stars requires --stars 1 to 5, or --stars clear to remove the rating.")
    text = str(value).strip().lower()
    if text in {"clear", "none"}:
        return None
    try:
        return validated_stars(int(text))
    except ValueError:
        raise ValueError(f"--stars must be a whole number from {MINIMUM_STARS} to {MAXIMUM_STARS}, or clear.") from None


def references_set_stars_on_behalf_of(flags: list[str], *, graphql: Any = None) -> None:
    """papyrus references set-stars --reference <id> --stars <1-5|clear> [--agent <your name>] [--dry-run]

    Rates as the person signed in to this CLI (papyrus login): their rating, recorded as theirs, with a plain note that it came through the CLI
    (and --agent's name). No delegation, code or approval is needed. It does not change the Reference's accept or reject, and it writes unless
    you pass --dry-run, which checks the arguments and prints what would be sent without contacting the Newsroom.

    Optional, for anyone who uses delegations: with --delegation-file <path> (or --delegation-token, or --on-behalf-of) it files the rating
    relayed under that delegation instead, which also needs --on-behalf-of <person's sign-in email>, --agent and --instruction "<the person's words>".
    """
    options = parse_options(flags)
    if options.get("help"):
        print(references_set_stars_on_behalf_of.__doc__)
        return
    apply = resolve_mutation_apply(options, "references set-stars")
    if not _uses_delegation(options):
        reference_id = options.get("reference") or options.get("reference-id")
        if not reference_id or reference_id is True:
            raise ValueError("references set-stars requires --reference <id>.")
        stars = _stars_option(options.get("stars"))
        agent_label = _agent_option(options)
        shown = "clear" if stars is None else str(stars)
        via = f"as the signed-in person via {agent_label}" if agent_label else "as the signed-in person"
        if not apply:
            print(f"references\tset-stars\t{reference_id}\t{shown}\t{via}\tdry-run: nothing sent")
            return
        if graphql is None:
            graphql = create_authoring_client()[0].graphql
        recorded = newsroom_reference_actions.set_reference_stars_as_signed_in_person(
            graphql, reference_id=str(reference_id), stars=stars, agent_label=agent_label)
        print(f"references\tset-stars\t{recorded.get('referenceId')}\t{'clear' if recorded.get('stars') is None else recorded.get('stars')}\t"
              f"{recorded.get('status') or ''}\t{via}")
        return
    reference_id, on_behalf_of, agent_label, token = _relay_arguments(options, "references set-stars")
    stars = _stars_option(options.get("stars"))
    shown = "clear" if stars is None else str(stars)
    if not apply:
        print(f"references\tset-stars\t{reference_id}\t{shown}\ton behalf of {on_behalf_of} via {agent_label}\tdry-run: nothing sent")
        return
    if graphql is None:
        graphql = create_authoring_client()[0].graphql
    recorded = newsroom_reference_actions.record_delegated_stars(
        graphql, reference_id=reference_id, stars=stars, delegation_token=token, agent_label=agent_label,
        on_behalf_of=on_behalf_of, instruction=str(options["instruction"]))
    print(f"references\tset-stars\t{recorded.get('referenceId')}\t{'clear' if recorded.get('stars') is None else recorded.get('stars')}\t"
          f"{recorded.get('status') or ''}\ton behalf of {on_behalf_of} via {agent_label}")


DELEGATION_REQUEST_POLL_INTERVAL_SECONDS = 5.0
DELEGATION_REQUEST_WAIT_TIMEOUT_SECONDS = 660.0


def default_delegation_token_path(delegation_id: str) -> Path:
    configuration_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(configuration_home) / "papyrus" / "delegations" / f"{delegation_id}.token"


def write_delegation_token_file(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(token)
    os.chmod(path, 0o600)


def references_request_delegation(
    flags: list[str],
    *,
    graphql: Any = None,
    sleep: Any = time.sleep,
    poll_interval_seconds: float = DELEGATION_REQUEST_POLL_INTERVAL_SECONDS,
    timeout_seconds: float = DELEGATION_REQUEST_WAIT_TIMEOUT_SECONDS,
) -> None:
    """papyrus references request-delegation --agent <your name> [--hours N] [--wait] [--token-file <path>]

    Asks for permission to relay a person's curation decisions without any secret passing through a person.
    The secret is made here and written to a private file; only its hash is sent. Tell the person the printed
    code. With --wait, polls until they approve or deny it. Then pass --delegation-file <path> to approve/reject.
    """
    options = parse_options(flags)
    agent_label = options.get("agent")
    if not agent_label or agent_label is True:
        raise ValueError("references request-delegation requires --agent.")
    hours = normalize_positive_integer(options.get("hours"), "--hours")
    if graphql is None:
        graphql = create_authoring_client()[0].graphql
    token = newsroom_reference_actions.new_delegation_token()
    delegation_id = newsroom_reference_actions.delegation_id_from_token(token)
    requested = newsroom_reference_actions.request_curation_delegation(
        graphql, delegation_token=token, agent_label=str(agent_label), hours=hours)
    user_code = str(requested.get("userCode") or "")
    if not user_code:
        raise ValueError("The Newsroom did not return an approval code.")
    given_path = options.get("token-file")
    token_path = Path(str(given_path)).expanduser() if given_path and given_path is not True else default_delegation_token_path(delegation_id)
    write_delegation_token_file(token_path, token)
    print(f"Open the Newsroom, Delegations, approve code {user_code}")
    print("Only a person in the Newsroom can approve it; this CLI session cannot.")
    print(f"The code expires at {requested.get('pendingExpiresAt')}. After approval, use --delegation-file {token_path}")
    if not options.get("wait"):
        return
    status = newsroom_reference_actions.wait_for_curation_delegation(
        graphql, delegation_id=delegation_id, poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds, sleep=sleep)
    state = status.get("state")
    if state == "approved":
        print(f"references\trequest-delegation\tapproved\tby {status.get('grantorLabel') or 'a person'}\texpires {status.get('expiresAt')}")
        return
    if status.get("timedOut"):
        raise ValueError("Timed out waiting for approval. The request stays valid until its code expires.")
    raise ValueError(f"The delegation request was {state}. Ask the person if you should request again.")


def references_list_predictions(flags: list[str]) -> None:
    options = parse_options(flags)
    limit = normalize_positive_integer(options.get("limit"), "--limit")
    status = str(options.get("status") or "current").lower()
    corpus_key = normalize_string(options.get("corpus-key"))
    category_set_id = normalize_string(options.get("category-set"))
    steering_config = load_steering_config(options.get("config")) if corpus_key else None
    corpus_id = (
        knowledge_corpus_id(require_corpus_config(steering_config, corpus_key, "--corpus-key"))
        if corpus_key and steering_config
        else None
    )
    client, _ = create_authoring_client()
    announce_full_read("references\tlist-predictions", "SemanticRelation, Reference", why="lists predictions across every Reference")
    relations = client.list_records("SemanticRelation")
    references = client.list_records("Reference")
    categories = client.list_records("Category")
    predictions = build_classification_prediction_rows(
        relations=relations,
        references=references,
        categories=categories,
        corpus_id=corpus_id,
        category_set_id=category_set_id,
        status=status,
        limit=limit,
    )
    for entry in predictions:
        print(
            "\t".join(
                [
                    entry["relation"]["id"],
                    entry["relation"].get("relationState") or "-",
                    entry["reference"].get("corpusId") or "-",
                    entry["reference"].get("externalItemId") or "-",
                    entry["reference"].get("title") or "-",
                    entry["category"].get("categoryKey") or entry["category"]["id"],
                    entry["category"].get("displayName") or "-",
                    "authoritative" if entry["hasAuthoritativeLabel"] else "predicted",
                ]
            )
        )
    if not predictions:
        print("references\tlist-predictions\t0")


def references_auto_accept(flags: list[str]) -> None:
    """``papyrus references auto-accept --site KEY [--dry-run]``: the router's automatic acceptance (src/papyrus_content/auto_accept.py) against one site."""
    from .auto_accept import validate_auto_accept, run_auto_accept
    options = parse_options(flags)
    site = normalize_string(options.get("site"))
    if not site:
        raise ValueError("references auto-accept needs --site KEY.")
    policy_input: dict[str, Any] = {}
    for flag, key in (("precision", "precision"), ("latency-quantile", "latencyQuantile")):
        if options.get(flag) is not None:
            try:
                policy_input[key] = float(options[flag])
            except ValueError as error:
                raise ValueError(f"--{flag} must be a number above 0 and below 1.") from error
    policy = validate_auto_accept(site, policy_input)
    corpus_key = normalize_string(options.get("corpus-key")) or site
    publication = {"publicationId": site, "corpusId": f"knowledge-corpus-{corpus_key}",
                   "positiveLabel": normalize_string(options.get("positive-label")) or "include"}
    client, _ = create_authoring_client()
    result = run_auto_accept(client, publication, policy, now=datetime.now(timezone.utc), dry_run=bool(options.get("dry-run")))
    print(json.dumps({"autoAccept": result["status"], **result}))
    from .auto_accept import run_rule_backfill
    backfill = run_rule_backfill(client, publication, now=datetime.now(timezone.utc), dry_run=bool(options.get("dry-run")))
    print(json.dumps({"autoAccept": "rule-backfill", **backfill}))


def references_suggest_links(flags: list[str]) -> None:
    """``papyrus references suggest-links --corpus-id ID --reference-id ID [--dry-run]``.

    Suggests related References and concepts for one Reference from the vector index (src/papyrus_content/reference_suggestions.py)
    and writes them as ``suggested`` links; ``--dry-run`` prints what would be written. The index is the one named by
    ``PAPYRUS_S3_VECTOR_INDEX_ARN`` or ``amplify_outputs.json``."""
    from papyrus_knowledge_query.services import S3VectorsProvider
    from papyrus_knowledge_query.vector_index import _vector_index_from_outputs

    from .reference_suggestions import suggest_for
    options = parse_options(flags)
    corpus_id = normalize_string(options.get("corpus-id"))
    reference_id = normalize_string(options.get("reference-id"))
    if not corpus_id or not reference_id:
        raise ValueError("references suggest-links needs --corpus-id ID and --reference-id ID.")
    apply = resolve_mutation_apply(options, "references suggest-links")
    index_arn = os.environ.get("PAPYRUS_S3_VECTOR_INDEX_ARN") or _vector_index_from_outputs()
    if not index_arn:
        raise RuntimeError("Missing PAPYRUS_S3_VECTOR_INDEX_ARN and custom.knowledgeQuery.s3VectorIndexArn")
    client, _ = create_authoring_client()
    provider = S3VectorsProvider(vector_index_arn=index_arn, region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
    from .suggestion_calibration import load_calibration
    print(json.dumps(suggest_for(client, provider, reference_id, corpus_id=corpus_id, calibration=load_calibration(client), dry_run=not apply), indent=2))


def references_retire_junk_suggestions(flags: list[str]) -> None:
    """``papyrus references retire-junk-suggestions [--execute]``.

    Lists the open ``auto:vector`` concept suggestions whose concept is a bookkeeping node (an author, a coverage, comment, quality-rating or relevance node;
    src/papyrus_content/junk_suggestions.py). It writes nothing unless ``--execute`` is given; then it marks each suggestion rejected (reason
    ``not_a_concept``, by ``auto:cleanup``), so it leaves the queue and is not offered again. Nothing is deleted."""
    from .junk_suggestions import retire_junk_suggestions
    options = parse_options(flags)
    client, _ = create_authoring_client()
    result = retire_junk_suggestions(client, execute=bool(options.get("execute")))
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
    for row in result["rows"]:
        print(f"references\tretire-junk-suggestions\t{'retired' if result['executed'] else 'would retire'}\t{row['relationId']}\t{row['nodeKind']}\t{row['nodeKey']}\t{row['score']}")


def references_backfill_feed_keys(flags: list[str]) -> None:
    """``papyrus references backfill-feed-keys (--site KEY | --corpus-key KEY[,KEY...] | --all-corpora) [--positive-label LABEL] [--dry-run]``.

    Sets the keys the References page pages through (src/papyrus_content/reference_feed_backfill.py) from each Reference's status and its
    current Cyclotron decision. It writes only those fields. ``--dry-run`` prints the counts and writes nothing. ``--site KEY`` covers
    ``knowledge-corpus-KEY``; ``--corpus-key`` names other corpora (comma-separated); ``--all-corpora`` covers every KnowledgeCorpus the
    backend lists. The backend is the one the CLI is configured for (docs/operator-cli.md), not something ``--site`` selects.
    """
    from .reference_feed_backfill import backfill_feed_keys, corpus_ids_for
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references backfill-feed-keys")
    from .operator_errors import require_operator_lane
    require_operator_lane("references backfill-feed-keys", "Reference records", writing=apply)
    client, _ = create_authoring_client()
    corpus_ids = corpus_ids_for(client, site=normalize_string(options.get("site")), corpus_keys=normalize_string(options.get("corpus-key")),
                                all_corpora=bool(options.get("all-corpora")))
    for corpus_id in corpus_ids:
        result = backfill_feed_keys(client, corpus_id=corpus_id, positive_label=normalize_string(options.get("positive-label")) or "include",
                                    dry_run=not apply,
                                    progress=lambda line: print(f"references\tbackfill-feed-keys\tprogress\t{line}") if int(line.split()[0]) % 100 == 0 else None)
        for key, value in result.items():
            print(f"references\tbackfill-feed-keys\t{key}\t{value}")


REQUEST_CHUNK = 100   # References per queue call: a transport size (one AppSync request must finish in 30 seconds), not a limit on the total


def references_queue_predictions(flags: list[str]) -> None:
    """``papyrus references queue-predictions (--site KEY | --corpus-key KEY[,KEY...]) [--dry-run]``.

    By hand, once: asks the site's cloud Cyclotron for a prediction for every current pending Reference that has none, by queueing one request per
    Reference exactly as a route does when it creates one (src/papyrus_content/reference_prediction_queue.py). It reads each corpus's prediction index
    (pending and voted partitions, highest first, down to the 0.5 an unpredicted row sorts at) and writes nothing to a Reference: the router decides the queued requests and records the decisions. A Reference already queued,
    or already predicted, is left alone. ``--dry-run`` prints the counts and queues nothing. Nothing schedules this command."""
    from .reference_feed_backfill import corpus_ids_for
    from .reference_prediction_queue import references_for_prediction, request_line, request_predictions, unpredicted_rows
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references queue-predictions")
    client, _ = create_authoring_client()
    corpus_ids = corpus_ids_for(client, site=normalize_string(options.get("site")), corpus_keys=normalize_string(options.get("corpus-key")), all_corpora=False)
    failed = False
    for corpus_id in corpus_ids:
        rows = list(unpredicted_rows(client, corpus_id))
        wanted = references_for_prediction(rows)
        print(f"references\tqueue-predictions\t{corpus_id}\tread\t{len(rows)}\twithout-prediction\t{len(wanted)}\t{'queue' if apply else 'dry-run'}")
        for start in range(0, len(wanted) if apply else 0, REQUEST_CHUNK):
            request = request_predictions(client, wanted[start:start + REQUEST_CHUNK])
            print(request_line(f"references\tqueue-predictions\t{corpus_id}", request))
            failed = failed or not request.ok
    if failed:
        raise ValueError("Some predictions were not requested; see the NOT-REQUESTED lines above.")


def references_queue_enrichment(flags: list[str]) -> None:
    """``papyrus references queue-enrichment (--site KEY | --corpus-key KEY[,KEY...]) [--dry-run]``.

    By hand, once, for the References created before every creation path asked for enrichment: queues one enrich-only request per current Reference whose
    content is not captured in full (src/papyrus_content/reference_prediction_queue.py, ``enrichment_source_id``). The router's ``email-references`` task
    then captures the text, writes the summary (and GROBID fields for a paper) and copies the curation onto the EXISTING Reference, exactly as it does for
    a new one; it decides nothing and creates nothing. It reads each corpus's feed index and writes nothing to a Reference. A Reference already queued is
    left alone, so a second run adds nothing. A video the cloud cannot fully capture is left for ``capture-thumbnails`` and ``capture-transcripts``, and
    the counts say how many. ``--dry-run`` prints the counts and queues nothing. Writing queue rows in production is for the owner to approve; nothing schedules this."""
    from .reference_feed_backfill import corpus_ids_for
    from .reference_prediction_queue import feed_rows, references_for_enrichment, request_line, request_predictions, video_line, videos_needing_local_run
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references queue-enrichment")
    client, _ = create_authoring_client()
    corpus_ids = corpus_ids_for(client, site=normalize_string(options.get("site")), corpus_keys=normalize_string(options.get("corpus-key")), all_corpora=False)
    failed = False
    for corpus_id in corpus_ids:
        rows = list(feed_rows(client, corpus_id))
        wanted = references_for_enrichment(rows)
        prefix = f"references\tqueue-enrichment\t{corpus_id}"
        print(f"{prefix}\tread\t{len(rows)}\tneeding-enrichment\t{len(wanted)}\t{'queue' if apply else 'dry-run'}")
        line = video_line(prefix, videos_needing_local_run(wanted))
        if line:
            print(line)
        for start in range(0, len(wanted) if apply else 0, REQUEST_CHUNK):
            request = request_predictions(client, wanted[start:start + REQUEST_CHUNK])
            print(request_line(prefix, request).replace("\tprediction\t", "\tenrichment\t"))
            failed = failed or not request.ok
    if failed:
        raise ValueError("Some enrichments were not requested; see the NOT-REQUESTED lines above.")


def references_backfill_medium(flags: list[str]) -> None:
    """``papyrus references backfill-medium (--site KEY | --corpus-key KEY[,KEY...] | --all-corpora) [--write]``.

    Sets ``medium``, ``playlistUrl``, ``evidenceLevel`` (aggregation only, only where empty), ``mediumFeedKey`` and ``contentNeededKey`` (the videos
    still waiting for content, for ``references capture-transcripts``) from each current Reference's address and stored capture state
    (src/papyrus_content/reference_medium_backfill.py). Unlike the other backfills it is SAFE BY DEFAULT: without ``--write`` it prints one
    line per Reference it would change and the counts, and writes nothing. ``--dry-run`` is accepted and means the same. Run it only after the
    site's data API has the fields and the index (docs/reference-feed-indexes.md#the-medium-index).
    """
    from .reference_feed_backfill import corpus_ids_for
    from .reference_medium_backfill import backfill_medium
    from .operator_errors import require_operator_lane
    options = parse_options(flags)
    write = parse_boolean_option(options.get("write"), default=False, label="--write") and not parse_boolean_option(options.get("dry-run"), default=False, label="--dry-run")
    require_operator_lane("references backfill-medium", "Reference records", writing=write)
    client, _ = create_authoring_client()
    corpus_ids = corpus_ids_for(client, site=normalize_string(options.get("site")), corpus_keys=normalize_string(options.get("corpus-key")),
                                all_corpora=bool(options.get("all-corpora")))
    print(f"references\tbackfill-medium\tmode\t{'write' if write else 'preview (nothing is written; add --write)'}")
    for corpus_id in corpus_ids:
        result = backfill_medium(client, corpus_id=corpus_id, dry_run=not write, progress=lambda line: print(f"references\tbackfill-medium\t{line}"))
        for key, value in result.items():
            print(f"references\tbackfill-medium\t{key}\t{value}")


def _word_table_name(options: dict[str, Any]) -> str:
    """``--word-table NAME``, else ``PAPYRUS_REFERENCE_WORD_TABLE``, else ``custom.referenceWordIndex.tableName`` of ``--outputs`` (default ``amplify_outputs.json``)."""
    import json
    import os
    from pathlib import Path

    named = normalize_string(options.get("word-table")) or os.environ.get("PAPYRUS_REFERENCE_WORD_TABLE", "").strip()
    if named:
        return named
    outputs = Path(normalize_string(options.get("outputs")) or "amplify_outputs.json")
    if outputs.is_file():
        found = ((json.loads(outputs.read_text(encoding="utf-8")).get("custom") or {}).get("referenceWordIndex") or {}).get("tableName")
        if found:
            return str(found)
    raise ValueError("references backfill-word-index needs the word table: --word-table NAME, PAPYRUS_REFERENCE_WORD_TABLE, or an amplify_outputs.json from a deploy that has it.")


def references_backfill_word_index(flags: list[str]) -> None:
    """``papyrus references backfill-word-index (--site KEY | --corpus-key KEY[,KEY...] | --all-corpora) [--word-table NAME] [--write]``.

    Writes the word rows the References search reads (src/papyrus_content/reference_word_backfill.py, docs/reference-search.md#word-index), once per site,
    right after the deploy that adds the word table and its stream consumer. SAFE BY DEFAULT: without ``--write`` it prints one line per Reference it
    would index and the counts, and writes nothing (``--dry-run`` means the same). It reads Reference rows by curation status, never a scan, and a Reference
    already indexed is skipped, so a second run writes nothing. It needs AWS credentials for the word table (the operator lane).
    """
    from .reference_feed_backfill import corpus_ids_for
    from .reference_word_backfill import backfill_words
    from .operator_errors import require_operator_lane
    from papyrus_knowledge_query.reference_words import WordWriter
    options = parse_options(flags)
    write = parse_boolean_option(options.get("write"), default=False, label="--write") and not parse_boolean_option(options.get("dry-run"), default=False, label="--dry-run")
    require_operator_lane("references backfill-word-index", "the word table", writing=write)
    client, _ = create_authoring_client()
    corpus_ids = corpus_ids_for(client, site=normalize_string(options.get("site")), corpus_keys=normalize_string(options.get("corpus-key")),
                                all_corpora=bool(options.get("all-corpora")))
    import boto3
    table = boto3.resource("dynamodb").Table(_word_table_name(options))
    writer = WordWriter(table, conflict_errors=(table.meta.client.exceptions.ConditionalCheckFailedException,))
    print(f"references\tbackfill-word-index\tmode\t{'write' if write else 'preview (nothing is written; add --write)'}")
    for corpus_id in corpus_ids:
        result = backfill_words(client, writer, corpus_id=corpus_id, dry_run=not write, progress=lambda line: print(f"references\tbackfill-word-index\t{line}"))
        for key, value in result.items():
            print(f"references\tbackfill-word-index\t{key}\t{value}")


def references_backfill_public_fields(flags: list[str]) -> None:
    """``papyrus references backfill-public-fields (--site KEY | --corpus-key KEY[,KEY...] | --all-corpora) [--write]``.

    Sets the public-blocks attributes on the rows a public page can show (docs/plans/public-blocks-from-indexes.md, src/papyrus_content/reference_public_fields.py):
    ``publicFeedKey`` and ``publicOrderKey`` on every accepted row and on every pending row with a stored prediction of at least 0.5, and ``cardImage``,
    ``cardSummary``, ``cardSiteName`` and ``cardPageTitle`` copied from each of those rows' preview (a video's picture is its own thumbnail copy). Rejected, archived, unpredicted and
    low-scored rows are not read or touched. This is the one command that reads preview attachments of existing rows; it is run once per site. Like
    ``backfill-medium`` it is SAFE BY DEFAULT: without ``--write`` it prints one line per row it would change and the counts, and writes nothing
    (``--dry-run`` is accepted and means the same). A second run writes nothing. Run ``backfill-feed-keys`` first on a site whose pending rows never got
    their prediction keys, and run this before the release that adds the index, so the index is complete the moment it is active.
    """
    from .reference_feed_backfill import corpus_ids_for
    from .reference_public_fields import backfill_public_fields
    from .operator_errors import require_operator_lane
    options = parse_options(flags)
    write = parse_boolean_option(options.get("write"), default=False, label="--write") and not parse_boolean_option(options.get("dry-run"), default=False, label="--dry-run")
    require_operator_lane("references backfill-public-fields", "Reference records", writing=write)
    client, _ = create_authoring_client()
    corpus_ids = corpus_ids_for(client, site=normalize_string(options.get("site")), corpus_keys=normalize_string(options.get("corpus-key")),
                                all_corpora=bool(options.get("all-corpora")))
    print(f"references\tbackfill-public-fields\tmode\t{'write' if write else 'preview (nothing is written; add --write)'}")
    for corpus_id in corpus_ids:
        result = backfill_public_fields(client, corpus_id=corpus_id, dry_run=not write, progress=lambda line: print(f"references\tbackfill-public-fields\t{line}"))
        for key, value in result.items():
            print(f"references\tbackfill-public-fields\t{key}\t{value}")


def references_retire_citation_stubs(flags: list[str]) -> None:
    """``papyrus references retire-citation-stubs --corpus-key KEY [--dry-run]``.

    Archives (never deletes) the pending References the GROBID citation graph created on its own and nobody has touched
    (src/papyrus_content/reference_citation_stubs.py). ``KEY`` is a corpus key (``ai-ml-research``) or a full corpus id
    (``knowledge-corpus-ai-ml-research``). ``--dry-run`` prints the counts and writes nothing.
    """
    from .reference_citation_stubs import retire_citation_stubs
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references retire-citation-stubs")
    key = normalize_string(options.get("corpus-key"))
    if not key or "," in key:
        raise ValueError("references retire-citation-stubs needs --corpus-key KEY (one corpus).")
    corpus_id = key if key.startswith("knowledge-corpus-") else f"knowledge-corpus-{key}"
    client, _ = create_authoring_client()
    result = retire_citation_stubs(client, corpus_id=corpus_id, dry_run=not apply,
                                   progress=lambda line: print(f"references\tretire-citation-stubs\tprogress\t{line}") if int(line.split()[0]) % 100 == 0 else None)
    for name, value in result.items():
        print(f"references\tretire-citation-stubs\t{name}\t{value}")


def references_duplicates(flags: list[str]) -> None:
    """``papyrus references duplicates [--format text|json] [--groups] [--skip-text-hashes]``

    Read-only. Groups the publication's current References by identity key (URL, arXiv id, DOI, captured text hash) and counts same-title
    groups as candidates only. It lists the References, and the attachments unless ``--skip-text-hashes``; it writes nothing.
    """
    from .reference_duplicates_report import build_duplicates_report, render_text

    options = parse_options(flags)
    output_format = normalize_string(options.get("format")) or "text"
    if output_format not in {"text", "json"}:
        raise ValueError("--format must be text or json.")
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = None if options.get("skip-text-hashes") else client.list_records("ReferenceAttachment")
    report = build_duplicates_report(references, attachments)
    if output_format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report, groups=bool(options.get("groups"))))


def references_backfill_reviewed_feed_key(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references backfill-reviewed-feed-key")
    from .operator_errors import require_operator_lane
    require_operator_lane("references backfill-reviewed-feed-key", "Reference records", writing=apply)
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    changes: list[dict[str, Any]] = []
    for reference in references:
        curation_status = str(reference.get("curationStatus") or "pending").strip().lower() or "pending"
        expected_reviewed_feed_key = None if curation_status == "pending" else "references#reviewed"
        if (reference.get("reviewedFeedKey") or None) == expected_reviewed_feed_key:
            continue
        expected = {**reference, "reviewedFeedKey": expected_reviewed_feed_key}
        changes.append({"current": reference, "expected": expected})
    print(f"references\tbackfill-reviewed-feed-key\tmode\t{'apply' if apply else 'dry-run'}")
    print(f"references\tbackfill-reviewed-feed-key\tscanned\t{len(references)}")
    print(f"references\tbackfill-reviewed-feed-key\tplanned\t{len(changes)}")
    for change in changes[:20]:
        current = change["current"]
        expected = change["expected"]
        print(
            "references\tbackfill-reviewed-feed-key\tcandidate\t"
            f"{current.get('id')}\t{current.get('curationStatus') or 'pending'}\t{expected.get('reviewedFeedKey') or '-'}"
        )
    if len(changes) > 20:
        print(f"references\tbackfill-reviewed-feed-key\tpreview-truncated\t{len(changes) - 20}")
    if not apply:
        print("references\tbackfill-reviewed-feed-key\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    for index, change in enumerate(changes, start=1):
        client.upsert("Reference", change["expected"])
        if index == len(changes) or index % 100 == 0:
            print(f"references\tbackfill-reviewed-feed-key\tprogress\t{index}/{len(changes)}")
    print(f"references\tbackfill-reviewed-feed-key\tupdated\t{len(changes)}")


def references_backfill_corpus_storage_paths(flags: list[str]) -> None:
    from .corpus_storage_paths import rewrite_corpus_storage_path
    from .env import storage_bucket_from_amplify_outputs

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references backfill-corpus-storage-paths")
    from .operator_errors import require_operator_lane
    require_operator_lane("references backfill-corpus-storage-paths", "Reference records", writing=apply)
    mirror_s3 = parse_boolean_option(options.get("mirror-s3"), False, "--mirror-s3")
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    corpus_key_by_id = {
        knowledge_corpus_id(entry): str(entry.get("key") or "")
        for entry in steering_config.get("corpora") or []
        if isinstance(entry, dict)
    }

    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    if reference_ids:
        reference_id_set = reference_ids
        lineage_ids = {
            str(reference.get("lineageId") or "")
            for reference in references
            if str(reference.get("id") or "") in reference_id_set
        }
        references = [
            reference
            for reference in references
            if str(reference.get("id") or "") in reference_id_set
            or str(reference.get("lineageId") or "") in lineage_ids
        ]
        attachments = [
            attachment
            for attachment in attachments
            if str(attachment.get("referenceId") or "") in reference_id_set
            or str(attachment.get("referenceLineageId") or "") in lineage_ids
        ]

    changes: list[dict[str, Any]] = []
    s3_pairs: list[tuple[str, str]] = []

    def plan_storage_path_update(model_name: str, record: dict[str, Any], field: str) -> None:
        current_path = normalize_string(record.get(field))
        if not current_path or not current_path.startswith("corpora/"):
            return
        record_corpus_id = normalize_string(record.get("corpusId"))
        if corpus_id and record_corpus_id and record_corpus_id != corpus_id:
            return
        record_corpus_key = corpus_key or corpus_key_by_id.get(record_corpus_id or "", "")
        rewritten = rewrite_corpus_storage_path(current_path, corpus_key=record_corpus_key or None)
        if not rewritten or rewritten == current_path:
            return
        expected = {**record, field: rewritten}
        changes.append({"modelName": model_name, "current": record, "expected": expected})
        s3_pairs.append((current_path, rewritten))

    for reference in references:
        plan_storage_path_update("Reference", reference, "storagePath")
    for attachment in attachments:
        plan_storage_path_update("ReferenceAttachment", attachment, "storagePath")

    print(f"references\tbackfill-corpus-storage-paths\tmode\t{'apply' if apply else 'dry-run'}")
    print(f"references\tbackfill-corpus-storage-paths\tcorpus\t{corpus_id or 'all'}")
    if reference_ids:
        print(f"references\tbackfill-corpus-storage-paths\treference-filter\t{len(reference_ids)}")
    print(f"references\tbackfill-corpus-storage-paths\tplanned\t{len(changes)}")
    print(f"references\tbackfill-corpus-storage-paths\tmirror-s3\t{str(mirror_s3).lower()}")
    for change in changes[:25]:
        current_path = change["current"].get("storagePath") or "-"
        expected_path = change["expected"].get("storagePath") or "-"
        print(
            "references\tbackfill-corpus-storage-paths\tcandidate\t"
            f"{change['modelName']}\t{change['current'].get('id')}\t{current_path}\t=>\t{expected_path}"
        )
    if len(changes) > 25:
        print(f"references\tbackfill-corpus-storage-paths\tpreview-truncated\t{len(changes) - 25}")
    if not apply:
        print("references\tbackfill-corpus-storage-paths\tapply\tskipped\tuse --dry-run to preview without writes")
        return

    bucket = storage_bucket_from_amplify_outputs()
    s3_client = None
    if mirror_s3 and bucket:
        try:
            import boto3  # type: ignore

            s3_client = boto3.client("s3")
        except ImportError:
            print("references\tbackfill-corpus-storage-paths\tmirror-s3\tskipped\tboto3 unavailable")
            mirror_s3 = False

    mirrored = 0
    mirror_skipped = 0
    mirror_failed = 0
    if mirror_s3 and s3_client and bucket:
        for old_key, new_key in dict.fromkeys(s3_pairs).items():
            try:
                s3_client.head_object(Bucket=bucket, Key=new_key)
                mirror_skipped += 1
                continue
            except Exception:  # noqa: BLE001
                pass
            try:
                s3_client.copy_object(
                    Bucket=bucket,
                    Key=new_key,
                    CopySource={"Bucket": bucket, "Key": old_key},
                )
                mirrored += 1
            except Exception as error:  # noqa: BLE001
                mirror_failed += 1
                print(
                    "references\tbackfill-corpus-storage-paths\tmirror-failed\t"
                    f"{old_key}\t{new_key}\t{error}"
                )
        print(f"references\tbackfill-corpus-storage-paths\tmirrored\t{mirrored}")
        print(f"references\tbackfill-corpus-storage-paths\tmirror-skipped-existing\t{mirror_skipped}")
        print(f"references\tbackfill-corpus-storage-paths\tmirror-failed\t{mirror_failed}")

    for index, change in enumerate(changes, start=1):
        client.upsert(change["modelName"], change["expected"])
        if index == len(changes) or index % 100 == 0:
            print(f"references\tbackfill-corpus-storage-paths\tprogress\t{index}/{len(changes)}")
    print(f"references\tbackfill-corpus-storage-paths\tupdated\t{len(changes)}")


def references_review_classification(flags: list[str]) -> None:
    options = parse_options(flags)
    relation_id = options.get("relation") or options.get("relation-id")
    action = str(options.get("action") or "").lower()
    if not relation_id:
        raise ValueError("references review-classification requires --relation <semantic-relation-id>.")
    if action not in {"accept", "reject"}:
        raise ValueError("references review-classification requires --action accept|reject.")
    client, _ = create_authoring_client()
    relation = client.get_record("SemanticRelation", relation_id)
    if not relation:
        raise ValueError(f"SemanticRelation {relation_id} was not found.")
    predicate = relation.get("relationTypeKey") or relation.get("predicate")
    if predicate != "classified_as":
        raise ValueError(f"SemanticRelation {relation_id} is not a classified_as prediction.")
    if relation.get("relationState") != "current":
        raise ValueError(
            f"SemanticRelation {relation_id} is {relation.get('relationState')}; only current predictions are reviewable."
        )
    if relation.get("subjectKind") != "reference" or relation.get("objectKind") != "category":
        raise ValueError(f"SemanticRelation {relation_id} must be reference -> category.")
    if action == "reject":
        client.delete_record("SemanticRelation", relation_id)
        update_newsroom_summary_delta(
            client,
            {
                "countDeltas": {"semanticRelations": -1},
                "facetDeltas": {
                    "semanticRelations": {
                        "byRelationTypeKey": {"classified_as": -1},
                        "byRelationDomain": {relation.get("relationDomain") or "unknown": -1},
                        "bySubjectKind": {relation.get("subjectKind") or "unknown": -1},
                        "byObjectKind": {relation.get("objectKind") or "unknown": -1},
                    },
                },
            },
            f"references review-classification reject {relation_id}",
        )
        print(f"references\treview-classification\t{relation_id}\treject\tdeleted_prediction")
        return
    authoritative = build_accept_authoritative_label_from_prediction(relation, note=options.get("note"))
    client.upsert("SemanticRelation", authoritative)
    update_newsroom_summary_delta(
        client,
        semantic_relation_count_delta(authoritative, 1),
        f"references review-classification accept {relation_id}",
    )
    print(f"references\treview-classification\t{relation_id}\taccept\t{authoritative['id']}")


def references_label(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("reference"):
        raise ValueError("references label requires --reference <reference-id|item-id>.")
    if not options.get("category"):
        raise ValueError("references label requires --category <category-key|lineage-id|id>.")
    if not options.get("category-set"):
        raise ValueError("references label requires --category-set <id>.")
    if not options.get("note"):
        raise ValueError("references label requires --note <text>.")
    client, _ = create_authoring_client()
    category_set = client.get_record("CategorySet", options["category-set"])
    if not category_set:
        raise ValueError(f"CategorySet {options['category-set']} was not found.")
    categories = client.list_records("Category")
    reference = resolve_reference_for_label(reference_by_token(client, options["reference"]), options["reference"])
    relations = subject_relations_for_references(client, [reference])   # find_current_authoritative_label only looks at this Reference's relations
    category = resolve_category_in_set(
        [entry for entry in categories if entry.get("categorySetId") == category_set["id"]],
        options["category"],
        label="--category",
    )
    if category.get("status") in {"deprecated", "archived"}:
        raise ValueError(f"Category {category['id']} is {category['status']}; label an active draft/current category.")
    authoritative = build_manual_authoritative_label_relation(
        reference=reference,
        category=category,
        category_set=category_set,
        note=options["note"],
        actor=options.get("actor") or "Papyrus content CLI",
    )
    existing = find_current_authoritative_label(relations, authoritative)
    if existing:
        print(
            f"references\tlabel\t{reference['id']}\t{category.get('categoryKey')}\tidempotent\t{existing['id']}"
        )
        return
    apply = resolve_mutation_apply(options, "references label")
    print_reference_label_plan("label", [authoritative], apply=apply)
    if not apply:
        print("references\tlabel\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    apply_label_relation(
        client,
        authoritative,
        reference_id=reference["id"],
        category_key=str(category.get("categoryKey") or category["id"]),
    )
    print(f"references\tlabel\t{reference['id']}\t{category.get('categoryKey')}\t{authoritative['id']}")


def references_promote(flags: list[str]) -> None:
    """papyrus references promote <reference> --section <section> [--actor-label <name>] [--dry-run]

    Saves a draft article for a monitor record (a delivered Hub model). Nothing is published; promoting twice changes nothing."""
    from .knowledge_snapshot.monitor_records import record_of
    from .monitor_promotion import promotion_item_id, promote_record, validate_section

    token, rest = (flags[0], flags[1:]) if flags and not flags[0].startswith("--") else (None, flags)
    options = parse_options(rest)
    token = token or normalize_string(options.get("reference"))
    if not token:
        raise ValueError("references promote requires a reference id: papyrus references promote <reference-id> --section <section>.")
    section = validate_section(options.get("section"))
    apply = resolve_mutation_apply(options, "references promote")
    client, _ = create_authoring_client()
    row = client.get_record("Reference", token) or resolve_reference_any(reference_by_token(client, token), token)
    record, _missing = record_of(row)
    item_id = promotion_item_id(record, section)
    print(f"references\tpromote\t{record.reference_id}\t{record.model_id}\t{section}\t{item_id}\t{'write' if apply else 'dry run'}")
    if not apply:
        return
    outcome = promote_record(client, record, section=section, actor=normalize_string(options.get("actor-label")) or "papyrus-cli")
    print(f"references\tpromote\t{record.reference_id}\t{outcome['itemId']}\t{'draft' if outcome['created'] else 'unchanged: already promoted'}\t{outcome['section']}/{outcome['slug']}\tbased on {','.join(outcome['linked'])}")


def references_unlabel(flags: list[str]) -> None:
    options = parse_options(flags)
    relation_id = options.get("relation") or options.get("relation-id")
    if not relation_id:
        raise ValueError("references unlabel requires --relation <authoritative-label-relation-id>.")
    client, _ = create_authoring_client()
    relation = client.get_record("SemanticRelation", relation_id)
    if not relation:
        raise ValueError(f"SemanticRelation {relation_id} was not found.")
    if (relation.get("relationTypeKey") or relation.get("predicate")) != "authoritative_label":
        raise ValueError(f"SemanticRelation {relation_id} is not an authoritative_label relation.")
    apply = resolve_mutation_apply(options, "references unlabel")
    print_reference_label_plan("unlabel", [relation], apply=apply)
    if not apply:
        print("references\tunlabel\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    apply_unlabel_relation(client, relation)
    print(f"references\tunlabel\t{relation_id}\tdeleted_authoritative_label")


def references_labels(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    categories = client.list_records("Category")
    if options.get("reference"):
        # One Reference: its rows and its own relations; build_label_rows keeps only that Reference's labels anyway.
        references = reference_by_token(client, options["reference"])
        reference = resolve_reference_any(references, options["reference"])
        relations = subject_relations_for_references(client, [reference])
    else:
        announce_full_read("references\tlabels", "Reference, SemanticRelation", why="lists the labels of every Reference")
        references = client.list_records("Reference")
        relations = client.list_records("SemanticRelation")
        reference = None
    category = None
    if options.get("category"):
        candidates = (
            [entry for entry in categories if entry.get("categorySetId") == options.get("category-set")]
            if options.get("category-set")
            else categories
        )
        category = resolve_category_any(candidates, options["category"])
    limit = normalize_positive_integer(options.get("limit"), "--limit")
    rows = build_label_rows(
        relations=relations,
        references=references,
        categories=categories,
        reference=reference,
        category=category,
        limit=limit,
    )
    for row in rows:
        print(
            "\t".join(
                [
                    row["relation"]["id"],
                    row["relation"].get("relationTypeKey") or row["relation"].get("predicate") or "-",
                    row["reference"].get("curationStatus") or "-",
                    row["reference"].get("externalItemId") or row["reference"]["id"],
                    row["reference"].get("title") or "-",
                    row["category"].get("categoryKey") or row["category"]["id"],
                    row["category"].get("displayName") or "-",
                    row["category"].get("categorySetId") or "-",
                ]
            )
        )
    if not rows:
        print("references\tlabels\t0")


def references_discover_citation_led(flags: list[str]) -> None:
    run_citation_led_discovery(flags)


def references_curate_recent(flags: list[str]) -> None:
    options = parse_options(flags)
    references = parse_repeated_option(flags, "reference")
    apply = resolve_mutation_apply(options, "references curate-recent")
    dry_run = parse_boolean_option(options.get("dry-run"), False, "--dry-run")
    json_output = parse_boolean_option(options.get("json"), False, "--json")
    if not options.get("corpus-key"):
        raise ValueError("references curate-recent requires --corpus-key <key>.")
    curate_all = parse_boolean_option(options.get("all"), False, "--all")
    if parse_boolean_option(options.get("refresh-quality"), False, "--refresh-quality"):
        raise ValueError(
            "references curate-recent no longer supports --refresh-quality. "
            "Quality is human-only; use references review-curation / quality actions explicitly."
        )
    args = [
        "run",
        "papyrus",
        "references",
        "curate-recent",
        "--corpus-key",
        options["corpus-key"],
        "--model",
        normalize_string(options.get("model")) or DEFAULT_REFERENCE_FILTER_MODEL,
        "--summary-max-tokens",
        str(normalize_non_negative_integer(options.get("summary-max-tokens"), "--summary-max-tokens") or 500),
        "--max-count",
        str(normalize_non_negative_integer(options.get("max-count"), "--max-count") or 0),
        "--scan-limit",
        str(normalize_positive_integer(options.get("scan-limit"), "--scan-limit") or 1000),
        "--max-parallel",
        str(normalize_positive_integer(options.get("max-parallel"), "--max-parallel") or 1),
    ]
    if curate_all:
        args.append("--all")
    else:
        args.extend(
            [
                "--since-hours",
                str(normalize_non_negative_integer(options.get("since-hours"), "--since-hours") or 48),
            ]
        )
    since = normalize_string(options.get("since"))
    if since:
        args.extend(["--since", since])
    resume = normalize_string(options.get("resume"))
    if resume:
        args.extend(["--resume", resume])
    for reference_id in references:
        args.extend(["--reference", reference_id])
    if parse_boolean_option(options.get("refresh-summary"), False, "--refresh-summary"):
        args.append("--refresh-summary")
    args.append("--dry-run")
    completed = subprocess.run(["poetry", *args], cwd=PAPYRUS_ROOT, capture_output=True, text=True, check=False)
    payload = extract_last_json_object(completed.stdout or "")
    if not payload:
        raise RuntimeError(
            "papyrus references curate-recent returned invalid JSON: "
            f"{completed.stderr or completed.stdout or 'unknown error'}"
        )
    if completed.returncode != 0:
        raise RuntimeError(f"papyrus references curate-recent exited with status {completed.returncode}")
    summary = payload.get("selectionSummary") or payload.get("summary") or {}
    selected_reference_ids = [
        normalize_string(value)
        for value in (payload.get("selectedReferenceIds") or [])
        if normalize_string(value)
    ]
    if not selected_reference_ids:
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            if item.get("failed"):
                continue
            reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
            reference_id = (
                normalize_string(reference.get("id"))
                or normalize_string(item.get("referenceId"))
            )
            if reference_id:
                selected_reference_ids.append(reference_id)
    selected_reference_ids = sorted(set(selected_reference_ids))
    dispatches: list[dict[str, Any]] = []
    if apply and selected_reference_ids:
        client, _ = create_authoring_client()
        actor_label = normalize_string(options.get("actor")) or "Papyrus content CLI"
        for reference_id in selected_reference_ids:
            result = newsroom_reference_actions.start_reference_curation(
                client.graphql,
                reference_id=reference_id,
                actor_label=actor_label,
                curation_policy=None,
            )
            dispatches.append(
                {
                    "referenceId": normalize_string(result.get("referenceId")) or reference_id,
                    "assignmentId": normalize_string(result.get("assignmentId")),
                    "status": normalize_string(result.get("status")) or "queued",
                    "runId": normalize_string(result.get("runId")),
                }
            )
    output = {
        "mode": "assignment_dispatch",
        "ok": bool(payload.get("ok", True)),
        "degraded": bool(payload.get("degraded", False)),
        "runId": payload.get("runId"),
        "manifestPath": payload.get("manifestPath"),
        "selectedReferenceIds": selected_reference_ids,
        "selectedCount": len(selected_reference_ids),
        "selectionSummary": summary,
        "selectionFailures": payload.get("selectionFailures") or [],
        "warnings": payload.get("warnings") or [],
        "apply": bool(apply and not dry_run),
        "dispatches": dispatches,
        "dispatchCount": len(dispatches),
    }
    if json_output:
        print(json.dumps(output, indent=2))
        return
    print(f"references\tcurate-recent\tmode\tassignment-dispatch")
    print(f"references\tcurate-recent\trun\t{payload.get('runId', '-')}")
    print(f"references\tcurate-recent\tmanifest\t{payload.get('manifestPath', '-')}")
    print(f"references\tcurate-recent\tselected\t{len(selected_reference_ids)}")
    print(f"references\tcurate-recent\tapply\t{'yes' if output['apply'] else 'no'}")
    print(f"references\tcurate-recent\tdispatches\t{len(dispatches)}")
    for reference_id in selected_reference_ids:
        print(f"reference-curation\tselected\t{reference_id}")
    for dispatch in dispatches:
        print(
            f"reference-curation\tdispatched\t{dispatch.get('referenceId') or '-'}\t"
            f"{dispatch.get('assignmentId') or '-'}\t{dispatch.get('status') or '-'}"
        )
    for failure in output["selectionFailures"]:
        if not isinstance(failure, dict):
            continue
        print(
            f"reference-curation\tselection-failed\t{failure.get('referenceId', '-')}\t"
            f"{failure.get('failureReason', 'selection failed')}"
        )
    for warning in output["warnings"]:
        print(f"references\tcurate-recent\twarning\t{warning}")


def references_extract_text_now(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-extract-text-now")
    if not options.get("corpus-key"):
        raise ValueError("references process-extract-text-now requires --corpus-key <key>.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    client, auth = create_authoring_client()
    now = _utc_now()
    actor_label = options.get("assignee-key") or options.get("assignee") or options.get("actor") or "Papyrus content CLI"
    run_id = options.get("run-id") or (
        f"reference-text-extraction-{timestamp_for_path(now)}-"
        f"{hash_short([corpus_id, options.get('stage'), options.get('configuration'), options.get('force')])}"
    )
    records = build_text_extraction_assignment_records(
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        actor_label=actor_label,
        now=now,
        options=options,
        run_id=run_id,
    )
    changes = build_record_changes(client, records)
    apply_record_changes(client, changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        changes,
        actor_label=actor_label,
        reason=f"references process-extract-text-now create {corpus_id}",
    )
    assignment_id = records[0]["expected"]["id"]
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="claim",
        assignment_id=assignment_id,
        options=options,
        actor_label=actor_label,
    )
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment {assignment_id} was not found after planning.")
    execution = execute_reference_text_extraction_assignment(client, assignment, options)
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="complete",
        assignment_id=assignment_id,
        options=options,
        actor_label=actor_label,
    )
    print(f"reference-text-extraction-now\tassignment\t{assignment_id}")
    print(f"reference-text-extraction-now\trun\t{execution['runId']}")
    print(f"reference-text-extraction-now\tmanifest\t{execution['manifestPath']}")
    print(f"reference-text-extraction-now\tattachments\t{execution['importSummary'].get('importedRecords', 0)}")


def references_attach_extracted_text(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-attach-extracted-text")
    if not options.get("corpus-key"):
        raise ValueError("references process-attach-extracted-text requires --corpus-key <key>.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    actor_label = options.get("actor") or "Papyrus content CLI"
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    extraction_index = build_extraction_index(corpus_config.get("path"))
    all_plans = build_extracted_text_attachment_plans(
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        references=references,
        attachments=attachments,
        extraction_index=extraction_index,
    )
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    plans = all_plans[:max_count] if max_count else all_plans
    records = [plan["record"] for plan in plans if plan.get("record")]
    changes = build_record_changes(client, records)
    print(f"references\tprocess-attach-extracted-text\tcorpus\t{corpus_id}")
    print(f"references\tprocess-attach-extracted-text\tsnapshots\t{len(extraction_index.snapshot_ids)}")
    print(f"references\tprocess-attach-extracted-text\teligible\t{len(all_plans)}")
    if max_count:
        print(f"references\tprocess-attach-extracted-text\tmax-count\t{max_count}")
    print(f"references\tprocess-attach-extracted-text\tsnapshot_attachments\t{len(plans)}")
    print(f"references\tprocess-attach-extracted-text\tplanned\t{len(records)}")
    changed = [change for change in changes if change.get("action") != "noop"]
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25
    print(f"references\tprocess-attach-extracted-text\tchanges\t{len(changed)}")
    for change in changed[:print_limit]:
        print(f"{change['action']}\t{change['modelName']}\t{change['expected']['id']}")
    if len(changed) > print_limit:
        print(
            f"references\tprocess-attach-extracted-text\tomitted\t{len(changed) - print_limit}\t"
            f"pass --limit {len(changed)} to print every planned change"
        )
    apply = resolve_mutation_apply(options, "references process-attach-extracted-text")
    if not apply:
        print(
            "references\tprocess-attach-extracted-text\tapply\tskipped\tuse --dry-run to preview without writes"
        )
        return
    apply_record_changes(client, changes)
    update_newsroom_summary_after_extracted_text_attachments(
        client,
        changes,
        actor_label=actor_label,
        reason=f"references process-attach-extracted-text {corpus_id}",
    )
    attached = len([change for change in changes if change.get("action") == "create"])
    print(f"references\tprocess-attach-extracted-text\tattached\t{attached}")


def references_find_url_text(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references find-fetch-url-text")
    actor_label = options.get("actor") or "Papyrus content CLI"
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    corpus_key_by_id = {
        knowledge_corpus_id(entry): str(entry.get("key") or "")
        for entry in steering_config.get("corpora") or []
        if isinstance(entry, dict)
    }
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    force = parse_boolean_option(options.get("force"), False, "--force")
    apply = resolve_mutation_apply(options, "references find-fetch-url-text")
    pdf_only = parse_boolean_option(options.get("pdf-only"), False, "--pdf-only")

    client, _ = create_authoring_client()
    scope = targeted_scope(client, reference_ids=reference_ids, external_item_ids=external_item_ids, corpus_id=corpus_id)
    if scope:
        references, attachments = scope["references"], scope["attachments"]
    else:
        announce_full_read("references\tfind-fetch-url-text", "Reference, ReferenceAttachment", why="no --reference or --external-item-id: sweeps the corpus")
        references = client.list_records("Reference")
        attachments = client.list_records("ReferenceAttachment")
    result = run_reference_source_find(
        client=client,
        references=references,
        attachments=attachments,
        corpus_key_by_id=corpus_key_by_id,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        apply=apply,
        bucket=normalize_string(options.get("bucket")),
        pdf_only=pdf_only,
    )

    print(f"references\tfind-fetch-url-text\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tfind-fetch-url-text\tstatus\t{curation_status}")
    print(f"references\tfind-fetch-url-text\tqueue-order\tnewest-first")
    print(f"references\tfind-fetch-url-text\tqueue-default\tmissing-only")
    print(f"references\tfind-fetch-url-text\tpdf-only\t{str(pdf_only).lower()}")
    if reference_ids:
        print(f"references\tfind-fetch-url-text\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tfind-fetch-url-text\texternal-item-filter\t{len(external_item_ids)}")
    print(f"references\tfind-fetch-url-text\teligible\t{result['eligibleCount']}")
    print(f"references\tfind-fetch-url-text\tskipped-existing\t{result['skippedExistingCount']}")
    print(f"references\tfind-fetch-url-text\tskipped-missing-source\t{result.get('skippedMissingSourceCount', 0)}")
    print(f"references\tfind-fetch-url-text\tskipped-non-pdf\t{result.get('skippedNonPdfCount', 0)}")
    print(f"references\tfind-fetch-url-text\tplanned\t{result['plannedCount']}")
    print(f"references\tfind-fetch-url-text\tplanned-attachments\t{result.get('plannedAttachmentCount', 0)}")
    print(f"references\tfind-fetch-url-text\tplanned-reference-metadata\t{result.get('plannedReferenceMetadataCount', 0)}")
    print(f"references\tfind-fetch-url-text\tchanges\t{result['changeCount']}")
    print(f"references\tfind-fetch-url-text\treference-metadata-changes\t{result.get('referenceMetadataChangeCount', 0)}")
    print(f"references\tfind-fetch-url-text\tattachment-changes\t{result.get('attachmentChangeCount', 0)}")
    print(f"references\tfind-fetch-url-text\tfailures\t{len(result['failures'])}")
    print(f"references\tfind-fetch-url-text\tdoi-resolved\t{result.get('doiResolvedCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-pdf-selected\t{result.get('doiPdfSelectedCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-pdf-missed\t{result.get('doiPdfMissedCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-search-used\t{result.get('doiSearchUsedCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-search-hit\t{result.get('doiSearchHitCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-api-fallback-used\t{result.get('doiApiFallbackUsedCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-paywalled-or-blocked\t{result.get('doiPaywalledOrBlockedCount', 0)}")
    if max_count:
        print(f"references\tfind-fetch-url-text\tmax-count\t{max_count}")
    changed = [change for change in result["changes"] if change.get("action") != "noop"]
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25
    for change in changed[:print_limit]:
        print(f"{change['action']}\t{change['modelName']}\t{change['expected']['id']}")
    for failure in result["failures"][:print_limit]:
        print(
            f"reference-find\tfailed\t{failure.get('referenceId') or '-'}\t"
            f"{failure.get('sourceUri') or '-'}\t{failure.get('error') or 'unknown error'}"
        )
    if not apply:
        print("references\tfind-fetch-url-text\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    update_newsroom_summary_after_extracted_text_attachments(
        client,
        result["changes"],
        actor_label=actor_label,
        reason=f"references find-fetch-url-text {corpus_id or 'all'}",
    )


def _read_references_for(client: Any, command: str, reference_ids: set[str], external_item_ids: set[str], corpus_id: str | None, *,
                         attachments: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None, dict[str, Any] | None]:
    """The References (and their attachments) a "process" command works on: the named ones by index, else the whole tables with a note saying so."""
    scope = targeted_scope(client, reference_ids=reference_ids, external_item_ids=external_item_ids, corpus_id=corpus_id)
    if scope:
        return scope["references"], scope["attachments"] if attachments else None, scope
    announce_full_read(f"references\t{command}", "Reference, ReferenceAttachment" if attachments else "Reference",
                       why="no --reference or --external-item-id: sweeps the corpus")
    return client.list_records("Reference"), client.list_records("ReferenceAttachment") if attachments else None, None


def _could_have_duplicates(references: list[dict[str, Any]], corpus_id: str | None, curation_status: str,
                           reference_ids: set[str], external_item_ids: set[str]) -> bool:
    """Whether two or more of the named References are in scope: identifier dedupe only merges References that are all named."""
    from .reference_url_text import _iter_candidate_references
    candidates = _iter_candidate_references(references=references, corpus_id=corpus_id, curation_status=curation_status,
                                            reference_ids=reference_ids, external_item_ids=external_item_ids)
    return len({str(row.get("lineageId") or row.get("id")) for row in candidates}) >= 2


def references_fetch_url_text(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-fetch-url-text")
    actor_label = options.get("actor") or "Papyrus content CLI"
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    corpus_key_by_id = {
        knowledge_corpus_id(entry): str(entry.get("key") or "")
        for entry in steering_config.get("corpora") or []
        if isinstance(entry, dict)
    }
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    force = parse_boolean_option(options.get("force"), False, "--force")
    apply = resolve_mutation_apply(options, "references process-fetch-url-text")
    bucket = normalize_string(options.get("bucket"))
    model = normalize_string(options.get("model")) or DEFAULT_REFERENCE_FILTER_MODEL
    pdf_only = parse_boolean_option(options.get("pdf-only"), False, "--pdf-only")
    from biblicus.grobid_runtime import ensure_grobid_running, resolve_grobid_base_url

    grobid_url = normalize_string(options.get("grobid-url")) or resolve_grobid_base_url()
    try:
        grobid_url = ensure_grobid_running(grobid_url)
    except RuntimeError as error:
        raise RuntimeError(
            "GROBID runtime preflight failed for references process-fetch-url-text. "
            f"endpoint={grobid_url} details={error}"
        ) from error

    client, _ = create_authoring_client()
    scope = targeted_scope(client, reference_ids=reference_ids, external_item_ids=external_item_ids, corpus_id=corpus_id)
    if scope:
        # Named References: read those rows and their attachments by index. The whole Reference and relation tables are read only if a
        # citation graph or a duplicate merge needs them (DeferredRows).
        references, attachments, semantic_relations = scope["references"], scope["attachments"], scope["relations"]
    else:
        announce_full_read("references\tprocess-fetch-url-text", "Reference, ReferenceAttachment, SemanticRelation", why="no --reference or --external-item-id: sweeps the corpus")
        references = client.list_records("Reference")
        attachments = client.list_records("ReferenceAttachment")
        semantic_relations = client.list_records("SemanticRelation")
    result = run_reference_url_text_extraction(
        client=client,
        references=references,
        all_references=scope["all_references"] if scope else None,
        attachments=attachments,
        semantic_relations=semantic_relations,
        corpus_key_by_id=corpus_key_by_id,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        apply=apply,
        bucket=bucket,
        model=model,
        pdf_only=pdf_only,
        grobid_url=grobid_url,
    )
    touched_reference_ids = {
        str((item.get("reference") or {}).get("id") or "")
        for item in (result.get("items") or [])
        if isinstance(item, dict) and isinstance(item.get("reference"), dict)
    }
    touched_reference_ids.update(
        {
            str((record.get("expected") or {}).get("id") or "")
            for record in (result.get("graphRecords") or [])
            if str(record.get("modelName") or "") == "Reference" and isinstance(record.get("expected"), dict)
        }
    )
    touched_reference_ids = {reference_id for reference_id in touched_reference_ids if reference_id}
    if scope and not _could_have_duplicates(scope["references"], corpus_id, curation_status, reference_ids, external_item_ids):
        # One named Reference has no duplicate among the named ones: nothing to merge, nothing to read.
        dedupe = {"records": [], "items": [], "changes": [], "changeCount": 0, "duplicateGroupCount": 0, "referencesMergedCount": 0,
                  "relationsRewiredCount": 0, "losersBlockedCount": 0}
    else:
        dedupe = run_reference_identifier_dedupe(
            client=client,
            references=scope["all_references"] if scope else client.list_records("Reference"),
            attachments=attachments,
            semantic_relations=scope["relations"] if scope else client.list_records("SemanticRelation"),
            corpus_id=corpus_id,
            reference_ids=reference_ids or None,
            external_item_ids=external_item_ids or None,
            curation_status=curation_status,
            touched_reference_ids=touched_reference_ids or None,
            force=force,
            apply=apply,
        )

    print(f"references\tprocess-fetch-url-text\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tprocess-fetch-url-text\tstatus\t{curation_status}")
    print(f"references\tprocess-fetch-url-text\tqueue-order\tnewest-first")
    print(f"references\tprocess-fetch-url-text\tqueue-default\tprocessable-only")
    print(f"references\tprocess-fetch-url-text\tpdf-only\t{str(pdf_only).lower()}")
    print(f"references\tprocess-fetch-url-text\tgrobid-url\t{grobid_url}")
    if reference_ids:
        print(f"references\tprocess-fetch-url-text\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tprocess-fetch-url-text\texternal-item-filter\t{len(external_item_ids)}")
    print(f"references\tprocess-fetch-url-text\teligible\t{result['eligibleCount']}")
    print(f"references\tprocess-fetch-url-text\tskipped-existing\t{result['skippedExistingCount']}")
    print(f"references\tprocess-fetch-url-text\tskipped-missing-source\t{result.get('skippedMissingSourceCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tskipped-needs-find\t{result.get('skippedNeedsFindCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tskipped-non-pdf\t{result.get('skippedNonPdfCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tplanned\t{result['plannedCount']}")
    print(f"references\tprocess-fetch-url-text\tplanned-attachments\t{result.get('plannedAttachmentCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tplanned-reference-metadata\t{result.get('plannedReferenceMetadataCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tauthors-parsed\t{result.get('authorsParsedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tauthors-linked\t{result.get('authorsLinkedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tcitations-parsed\t{result.get('citationsParsedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tcitations-upserted\t{result.get('citationsUpsertedCount', 0)}")
    print(
        f"references\tprocess-fetch-url-text\tcitations-skipped-low-confidence\t"
        f"{result.get('citationsSkippedLowConfidenceCount', 0)}"
    )
    print(
        f"references\tprocess-fetch-url-text\tcitation-relations-created\t"
        f"{result.get('citationRelationsCreatedCount', 0)}"
    )
    print(f"references\tprocess-fetch-url-text\tcitation-graph-warnings\t{len(result.get('citationGraphWarnings') or [])}")
    print(f"references\tprocess-fetch-url-text\tfiltered\t{result.get('filteredCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tfallback-raw\t{result.get('fallbackRawCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tchanges\t{result['changeCount']}")
    print(f"references\tprocess-fetch-url-text\tgraph-changes\t{result.get('graphChangeCount', 0)}")
    print(f"references\tprocess-fetch-url-text\treference-metadata-changes\t{result.get('referenceMetadataChangeCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tattachment-changes\t{result.get('attachmentChangeCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tfailures\t{len(result['failures'])}")
    print(f"references\tprocess-fetch-url-text\tfailed-grobid\t{result.get('failedGrobidCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-resolved\t{result.get('doiResolvedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-pdf-selected\t{result.get('doiPdfSelectedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-pdf-missed\t{result.get('doiPdfMissedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-search-used\t{result.get('doiSearchUsedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-search-hit\t{result.get('doiSearchHitCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-api-fallback-used\t{result.get('doiApiFallbackUsedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-paywalled-or-blocked\t{result.get('doiPaywalledOrBlockedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tduplicate-groups-found\t{dedupe.get('duplicateGroupCount', 0)}")
    print(f"references\tprocess-fetch-url-text\treferences-merged\t{dedupe.get('referencesMergedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\trelations-rewired\t{dedupe.get('relationsRewiredCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tlosers-blocked\t{dedupe.get('losersBlockedCount', 0)}")
    if max_count:
        print(f"references\tprocess-fetch-url-text\tmax-count\t{max_count}")
    if model:
        print(f"references\tprocess-fetch-url-text\tmodel\t{model}")
    changed = [change for change in result["changes"] if change.get("action") != "noop"]
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25
    for change in changed[:print_limit]:
        print(f"{change['action']}\t{change['modelName']}\t{change['expected']['id']}")
    if len(changed) > print_limit:
        print(
            f"references\tprocess-fetch-url-text\tomitted\t{len(changed) - print_limit}\t"
            f"pass --limit {len(changed)} to print every planned change"
        )
    for failure in result["failures"][:print_limit]:
        print(
            f"reference-url-text\tfailed\t{failure.get('referenceId') or '-'}\t"
            f"{failure.get('sourceUri') or '-'}\t{failure.get('error') or 'unknown error'}"
        )
    for fallback in (result.get("filterFallbacks") or [])[:print_limit]:
        print(
            f"reference-url-text\tfilter-fallback\t{fallback.get('referenceId') or '-'}\t"
            f"{fallback.get('sourceUri') or '-'}\t"
            f"{json.dumps(fallback.get('reason') or {}, sort_keys=True)}"
        )
    needs_find_rows = [
        item for item in (result.get("items") or [])
        if str(item.get("status") or "") == "needs_find"
    ]
    for row in needs_find_rows[:print_limit]:
        reference = row.get("reference") if isinstance(row.get("reference"), dict) else {}
        reason = row.get("error") if isinstance(row.get("error"), dict) else {"code": "needs_find", "message": "requires find"}
        print(
            f"reference-url-text\tneeds-find\t{reference.get('id') or '-'}\t"
            f"{reference.get('sourceUri') or '-'}\t{json.dumps(reason, sort_keys=True)}"
        )
    if len(result["failures"]) > print_limit:
        print(
            f"references\tprocess-fetch-url-text\tomitted-failures\t{len(result['failures']) - print_limit}\t"
            f"pass --limit {len(result['failures'])} to print every failure"
        )
    if not apply:
        print("references\tprocess-fetch-url-text\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    update_newsroom_summary_after_extracted_text_attachments(
        client,
        result["changes"],
        actor_label=actor_label,
        reason=f"references process-fetch-url-text {corpus_id or 'all'}",
    )
    created = len([change for change in result["changes"] if change.get("action") == "create"])
    print(f"references\tprocess-fetch-url-text\tattached\t{created}")


def references_fetch_pdf_url_text_queue(flags: list[str]) -> None:
    options = parse_options(flags)
    if options.get("pdf-only") is None:
        flags = [*flags, "--pdf-only", "true"]
    references_fetch_url_text(flags)


def references_find_pdf_url_text_queue(flags: list[str]) -> None:
    options = parse_options(flags)
    if options.get("pdf-only") is None:
        flags = [*flags, "--pdf-only", "true"]
    references_find_url_text(flags)


def references_recount_citation_counts(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-recount-citation-counts")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    apply = resolve_mutation_apply(options, "references process-recount-citation-counts")
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25

    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    semantic_relations = client.list_records("SemanticRelation")
    recount = build_reference_citation_count_records(
        references=references,
        semantic_relations=semantic_relations,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
    )
    changes = build_record_changes_targeted_by_id(client, recount["records"])
    changed = [change for change in changes if change.get("action") != "noop"]

    print(f"references\tprocess-recount-citation-counts\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tprocess-recount-citation-counts\tstatus\t{curation_status}")
    if reference_ids:
        print(f"references\tprocess-recount-citation-counts\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tprocess-recount-citation-counts\texternal-item-filter\t{len(external_item_ids)}")
    print(f"references\tprocess-recount-citation-counts\treferences\t{recount['referenceCount']}")
    print(f"references\tprocess-recount-citation-counts\tchanges\t{len(changed)}")
    for item in recount["items"][:print_limit]:
        reference = item["reference"]
        print(
            "\t".join(
                [
                    "reference-citation-count",
                    reference.get("id") or "-",
                    reference.get("externalItemId") or "-",
                    str(item.get("inboundCitationCount") or 0),
                    str(item.get("outboundCitationCount") or 0),
                ]
            )
        )
    if len(recount["items"]) > print_limit:
        print(
            f"references\tprocess-recount-citation-counts\tomitted\t{len(recount['items']) - print_limit}\t"
            f"pass --limit {len(recount['items'])} to print every row"
        )
    if not apply:
        print(
            "references\tprocess-recount-citation-counts\tapply\tskipped\t"
            "use --dry-run to preview without writes"
        )
        return
    apply_record_changes(client, changed)


def references_process_dedupe_identifiers(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-dedupe-identifiers")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    force = parse_boolean_option(options.get("force"), False, "--force")
    apply = resolve_mutation_apply(options, "references process-dedupe-identifiers")
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25

    client, _ = create_authoring_client()
    scope = targeted_scope(client, reference_ids=reference_ids, external_item_ids=external_item_ids, corpus_id=corpus_id)
    if scope and not _could_have_duplicates(scope["references"], corpus_id, curation_status, reference_ids, external_item_ids):
        # Identifier dedupe only merges References that are all named; fewer than two are in scope, so there is nothing to find or read.
        dedupe = {"duplicateGroupCount": 0, "referencesMergedCount": 0, "relationsRewiredCount": 0, "losersBlockedCount": 0, "changes": [], "changeCount": 0, "items": []}
    else:
        if scope:
            references, attachments, semantic_relations = scope["all_references"], scope["attachments"], scope["relations"]
        else:
            announce_full_read("references\tprocess-dedupe-identifiers", "Reference, ReferenceAttachment, SemanticRelation", why="finds duplicates across the corpus")
            references = client.list_records("Reference")
            attachments = client.list_records("ReferenceAttachment")
            semantic_relations = client.list_records("SemanticRelation")
        dedupe = run_reference_identifier_dedupe(
            client=client,
            references=references,
            attachments=attachments,
            semantic_relations=semantic_relations,
            corpus_id=corpus_id,
            reference_ids=reference_ids or None,
            external_item_ids=external_item_ids or None,
            curation_status=curation_status,
            touched_reference_ids=None,
            force=force,
            apply=apply,
        )

    print(f"references\tprocess-dedupe-identifiers\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tprocess-dedupe-identifiers\tstatus\t{curation_status}")
    if reference_ids:
        print(f"references\tprocess-dedupe-identifiers\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tprocess-dedupe-identifiers\texternal-item-filter\t{len(external_item_ids)}")
    print(f"references\tprocess-dedupe-identifiers\tduplicate-groups-found\t{dedupe.get('duplicateGroupCount', 0)}")
    print(f"references\tprocess-dedupe-identifiers\treferences-merged\t{dedupe.get('referencesMergedCount', 0)}")
    print(f"references\tprocess-dedupe-identifiers\trelations-rewired\t{dedupe.get('relationsRewiredCount', 0)}")
    print(f"references\tprocess-dedupe-identifiers\tlosers-blocked\t{dedupe.get('losersBlockedCount', 0)}")
    print(f"references\tprocess-dedupe-identifiers\tchanges\t{dedupe.get('changeCount', 0)}")
    for item in (dedupe.get("items") or [])[:print_limit]:
        print(
            "\t".join(
                [
                    "reference-dedupe",
                    str(item.get("loserId") or "-"),
                    str(item.get("loserLineageId") or "-"),
                    str(item.get("winnerId") or "-"),
                    str(item.get("winnerLineageId") or "-"),
                ]
            )
        )
    if len(dedupe.get("items") or []) > print_limit:
        print(
            f"references\tprocess-dedupe-identifiers\tomitted\t{len(dedupe['items']) - print_limit}\t"
            f"pass --limit {len(dedupe['items'])} to print every row"
        )
    if not apply:
        print(
            "references\tprocess-dedupe-identifiers\tapply\tskipped\t"
            "use --dry-run to preview without writes"
        )


def references_process_resolve_citation_stubs(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references find-resolve-citation-stubs")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    force = parse_boolean_option(options.get("force"), False, "--force")
    promote_external_id = parse_boolean_option(options.get("promote-external-id"), False, "--promote-external-id")
    apply = resolve_mutation_apply(options, "references find-resolve-citation-stubs")
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25

    client, _ = create_authoring_client()
    references, _attachments, _scope = _read_references_for(client, "find-resolve-citation-stubs", reference_ids, external_item_ids, corpus_id, attachments=False)
    resolved = build_reference_citation_resolution_records(
        references=references,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        promote_external_id=promote_external_id,
    )
    changes = build_record_changes_targeted_by_id(client, resolved["records"])
    changed = [change for change in changes if change.get("action") != "noop"]

    print(f"references\tfind-resolve-citation-stubs\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tfind-resolve-citation-stubs\tstatus\t{curation_status}")
    if reference_ids:
        print(f"references\tfind-resolve-citation-stubs\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tfind-resolve-citation-stubs\texternal-item-filter\t{len(external_item_ids)}")
    if max_count:
        print(f"references\tfind-resolve-citation-stubs\tmax-count\t{max_count}")
    print(f"references\tfind-resolve-citation-stubs\tattempted\t{resolved['attemptedCount']}")
    print(f"references\tfind-resolve-citation-stubs\tresolved\t{resolved['resolvedCount']}")
    print(f"references\tfind-resolve-citation-stubs\tskipped-existing\t{resolved['skippedExistingCount']}")
    print(f"references\tfind-resolve-citation-stubs\tskipped-non-citation\t{resolved['skippedNonCitationCount']}")
    print(f"references\tfind-resolve-citation-stubs\tfailures\t{resolved['failureCount']}")
    print(f"references\tfind-resolve-citation-stubs\tchanges\t{len(changed)}")

    for item in resolved["items"][:print_limit]:
        best = item.get("bestCandidate") if isinstance(item.get("bestCandidate"), dict) else {}
        print(
            "\t".join(
                [
                    "reference-citation-resolve",
                    str(item.get("status") or ""),
                    str(item.get("referenceId") or "-"),
                    str(item.get("externalItemId") or "-"),
                    str(best.get("doi") or best.get("arxiv_id") or best.get("isbn") or "-"),
                    str(best.get("source_uri") or "-"),
                    str(best.get("score") or "-"),
                ]
            )
        )
    if len(resolved["items"]) > print_limit:
        print(
            f"references\tfind-resolve-citation-stubs\tomitted\t{len(resolved['items']) - print_limit}\t"
            f"pass --limit {len(resolved['items'])} to print every row"
        )
    if not apply:
        print(
            "references\tfind-resolve-citation-stubs\tapply\tskipped\t"
            "use --dry-run to preview without writes"
        )
        return
    apply_record_changes(client, changed)


def references_filter_extracted_text(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-filter-text")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    force = parse_boolean_option(options.get("force"), True, "--force")
    apply = resolve_mutation_apply(options, "references process-filter-text")
    bucket = normalize_string(options.get("bucket"))
    model = normalize_string(options.get("model")) or DEFAULT_REFERENCE_FILTER_MODEL
    metadata_from_text = parse_boolean_option(options.get("metadata-from-text"), True, "--metadata-from-text")
    metadata_model = normalize_string(options.get("metadata-model")) or DEFAULT_REFERENCE_SUMMARY_MODEL

    client, _ = create_authoring_client()
    references, attachments, scope = _read_references_for(client, "process-filter-text", reference_ids, external_item_ids, corpus_id)
    result = run_reference_extracted_text_filtering(
        client=client,
        references=references,
        attachments=attachments,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        model=model,
        apply=apply,
        bucket=bucket,
    )

    print(f"references\tprocess-filter-text\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tprocess-filter-text\tstatus\t{curation_status}")
    if reference_ids:
        print(f"references\tprocess-filter-text\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tprocess-filter-text\texternal-item-filter\t{len(external_item_ids)}")
    if max_count:
        print(f"references\tprocess-filter-text\tmax-count\t{max_count}")
    print(f"references\tprocess-filter-text\tmodel\t{model}")
    print(f"references\tprocess-filter-text\tattempted\t{result['attemptedCount']}")
    print(f"references\tprocess-filter-text\tplanned\t{result['plannedCount']}")
    print(f"references\tprocess-filter-text\tplanned-attachments\t{result['plannedAttachmentCount']}")
    print(f"references\tprocess-filter-text\tfiltered\t{result['filteredCount']}")
    print(f"references\tprocess-filter-text\tfallback-raw\t{result['fallbackRawCount']}")
    print(f"references\tprocess-filter-text\tskipped-missing-source\t{result['skippedMissingSourceCount']}")
    print(f"references\tprocess-filter-text\tchanges\t{result['changeCount']}")
    print(f"references\tprocess-filter-text\tfailures\t{len(result['failures'])}")

    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25
    for item in (result.get("items") or [])[:print_limit]:
        reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
        error = item.get("error") or {}
        if not isinstance(error, dict):
            error = {"message": str(error)}
        print(
            "\t".join(
                [
                    "reference-filter-text",
                    str(item.get("status") or ""),
                    str(reference.get("id") or "-"),
                    str(reference.get("externalItemId") or "-"),
                    json.dumps(error, sort_keys=True) if error else "",
                ]
            )
        )
    if len(result.get("items") or []) > print_limit:
        print(
            f"references\tprocess-filter-text\tomitted\t{len(result['items']) - print_limit}\t"
            f"pass --limit {len(result['items'])} to print every row"
        )
    for failure in result["failures"][:print_limit]:
        print(
            f"reference-filter-text\tfailed\t{failure.get('referenceId') or '-'}\t"
            f"{failure.get('sourceUri') or '-'}\t{failure.get('error') or 'unknown error'}"
        )
    for fallback in (result.get("filterFallbacks") or [])[:print_limit]:
        print(
            f"reference-filter-text\tfallback-raw\t{fallback.get('referenceId') or '-'}\t"
            f"{fallback.get('sourceUri') or '-'}\t{json.dumps(fallback.get('reason') or {}, sort_keys=True)}"
        )
    if len(result["failures"]) > print_limit:
        print(
            f"references\tprocess-filter-text\tomitted-failures\t{len(result['failures']) - print_limit}\t"
            f"pass --limit {len(result['failures'])} to print every failure"
        )
    if not apply:
        print("references\tprocess-filter-text\tapply\tskipped\tuse --dry-run to preview without writes")
        return

    actor_label = options.get("actor") or "Papyrus content CLI"
    update_newsroom_summary_after_extracted_text_attachments(
        client,
        result["changes"],
        actor_label=actor_label,
        reason=f"references process-filter-text {corpus_id or 'all'}",
    )

    if not metadata_from_text:
        print("references\tprocess-generate-metadata\tdisabled")
        return

    processed_reference_ids = set(result.get("processedReferenceIds") or [])
    if not processed_reference_ids:
        print("references\tprocess-generate-metadata\tskipped\tno references processed by filter step")
        return
    refreshed_attachments = (
        attachments_for_references(client, [row for row in references if row.get("id") in processed_reference_ids or row.get("lineageId") in processed_reference_ids])
        if scope else client.list_records("ReferenceAttachment")
    )
    generation = run_reference_metadata_generation_from_extracted_text(
        references=references,
        attachments=refreshed_attachments,
        corpus_id=corpus_id,
        reference_ids=processed_reference_ids,
        curation_status="all",
        model=metadata_model,
        apply=True,
        bucket=bucket,
    )
    print(f"references\tprocess-generate-metadata\tmodel\t{metadata_model}")
    print(f"references\tprocess-generate-metadata\tattempted\t{generation['attemptedCount']}")
    print(f"references\tprocess-generate-metadata\tgenerated\t{generation['generatedCount']}")
    print(f"references\tprocess-generate-metadata\tskipped-missing-text\t{generation['skippedMissingTextCount']}")
    print(f"references\tprocess-generate-metadata\tgeneration-failures\t{generation['generationFailureCount']}")


def references_generate_metadata_from_text(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-generate-metadata")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    apply = resolve_mutation_apply(options, "references process-generate-metadata")
    model = normalize_string(options.get("model")) or DEFAULT_REFERENCE_SUMMARY_MODEL
    bucket = normalize_string(options.get("bucket"))

    client, _ = create_authoring_client()
    references, attachments, _scope = _read_references_for(client, "process-generate-metadata", reference_ids, external_item_ids, corpus_id)
    result = run_reference_metadata_generation_from_extracted_text(
        references=references,
        attachments=attachments,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        max_count=max_count,
        model=model,
        apply=apply,
        bucket=bucket,
    )

    print(f"references\tprocess-generate-metadata\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tprocess-generate-metadata\tstatus\t{curation_status}")
    if reference_ids:
        print(f"references\tprocess-generate-metadata\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tprocess-generate-metadata\texternal-item-filter\t{len(external_item_ids)}")
    if max_count:
        print(f"references\tprocess-generate-metadata\tmax-count\t{max_count}")
    print(f"references\tprocess-generate-metadata\tattempted\t{result['attemptedCount']}")
    print(f"references\tprocess-generate-metadata\tgenerated\t{result['generatedCount']}")
    print(f"references\tprocess-generate-metadata\tskipped-missing-text\t{result['skippedMissingTextCount']}")
    print(f"references\tprocess-generate-metadata\tgeneration-failures\t{result['generationFailureCount']}")

    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25
    for item in result["items"][:print_limit]:
        reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
        print(
            "\t".join(
                [
                    "reference-metadata",
                    str(item.get("status") or ""),
                    str(reference.get("id") or "-"),
                    str(reference.get("externalItemId") or "-"),
                    str(item.get("error") or ""),
                ]
            )
        )
    if len(result["items"]) > print_limit:
        print(
            f"references\tprocess-generate-metadata\tomitted\t{len(result['items']) - print_limit}\t"
            f"pass --limit {len(result['items'])} to print every row"
        )
    if not apply:
        print(
            "references\tprocess-generate-metadata\tapply\tskipped\t"
            "use --dry-run to preview without writes"
        )


def references_create_identifier_backfill_assignment(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("corpus-key"):
        raise ValueError("references create-identifier-backfill-assignment requires --corpus-key <key>.")
    actor_label = options.get("actor") or "papyrus-cli"
    now = _utc_now()
    types = normalize_identifier_types(options.get("types"))
    run_id = options.get("run-id") or (
        f"reference-identifier-backfill-{timestamp_for_path(now)}-{hash_short([options['corpus-key'], ','.join(types)])}"
    )
    client, _ = create_authoring_client()
    assignment_plan = build_reference_identifier_backfill_assignment_plan(
        options=options,
        actor_label=actor_label,
        now=now,
        run_id=run_id,
        types=types,
    )
    changes = build_record_changes_targeted_by_id(client, assignment_plan["records"])
    print(f"references\tcreate-identifier-backfill-assignment\tassignment\t{assignment_plan['assignment']['id']}")
    print(f"references\tcreate-identifier-backfill-assignment\tcorpus\t{assignment_plan['corpusId']}")
    print(f"references\tcreate-identifier-backfill-assignment\ttypes\t{','.join(types)}")
    print(f"references\tcreate-identifier-backfill-assignment\trun\t{run_id}")
    for change in changes:
        print(f"{change['action']}\t{change['modelName']}\t{change['expected']['id']}")
    apply = resolve_mutation_apply(options, "references create-identifier-backfill-assignment")
    if not apply:
        print(
            "references\tcreate-identifier-backfill-assignment\tapply\tskipped\tuse --dry-run to preview without writes"
        )
        return
    apply_record_changes(client, changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        changes,
        actor_label=actor_label,
        reason=f"references create-identifier-backfill-assignment {assignment_plan['assignment']['id']}",
    )


def references_identifier_backfill_now(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("corpus-key"):
        raise ValueError("references identifier-backfill-now requires --corpus-key <key>.")
    now = _utc_now()
    types = normalize_identifier_types(options.get("types"))
    run_now_options = {
        **options,
        "apply": True,
        "run-id": options.get("run-id") or f"reference-identifier-backfill-now-{timestamp_for_path(now)}",
        "types": ",".join(types),
    }
    actor_label = (
        run_now_options.get("assignee-key")
        or run_now_options.get("assignee")
        or run_now_options.get("actor")
        or "papyrus-cli"
    )
    client, auth = create_authoring_client()
    assignment_plan = build_reference_identifier_backfill_assignment_plan(
        options=run_now_options,
        actor_label=actor_label,
        now=now,
        run_id=run_now_options["run-id"],
        types=types,
    )
    run_now_options["__assignmentMetadata"] = assignment_plan["metadata"]
    assignment_changes = build_record_changes_targeted_by_id(client, assignment_plan["records"])
    apply_record_changes(client, assignment_changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        assignment_changes,
        actor_label=actor_label,
        reason=f"references identifier-backfill-now create {assignment_plan['assignment']['id']}",
    )
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="claim",
        assignment_id=assignment_plan["assignment"]["id"],
        options=run_now_options,
        actor_label=actor_label,
    )
    execution_result = execute_assignment_by_type(
        client,
        assignment_plan["assignment"]["id"],
        run_now_options,
    )
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="complete",
        assignment_id=assignment_plan["assignment"]["id"],
        options=run_now_options,
        actor_label=actor_label,
    )
    summary = execution_result.get("summary") or {}
    print(f"references-identifier-backfill-now\tassignment\t{assignment_plan['assignment']['id']}")
    print(f"references-identifier-backfill-now\trun\t{execution_result.get('runId')}")
    print(f"references-identifier-backfill-now\tmanifest\t{execution_result.get('manifestPath')}")
    print(f"references-identifier-backfill-now\tresolved\t{summary.get('resolved', 0)}")
    print(f"references-identifier-backfill-now\tunresolved\t{summary.get('unresolved', 0)}")


def references_execute_identifier_backfill(flags: list[str]) -> None:
    options = parse_options(flags)
    assignment_id = options.get("assignment")
    if not assignment_id:
        raise ValueError("references execute-identifier-backfill requires --assignment <id>.")
    client, _ = create_authoring_client()
    execute_assignment_by_type(client, assignment_id, options)


def references_create_doi_backfill_assignment(flags: list[str]) -> None:
    references_create_identifier_backfill_assignment(doi_backfill_compatibility_flags(flags))


def references_doi_backfill_now(flags: list[str]) -> None:
    references_identifier_backfill_now(doi_backfill_compatibility_flags(flags))


def references_execute_doi_backfill(flags: list[str]) -> None:
    options = parse_options(doi_backfill_compatibility_flags(flags))
    assignment_id = options.get("assignment")
    if not assignment_id:
        raise ValueError("references execute-doi-backfill requires --assignment <id>.")
    client, _ = create_authoring_client()
    execute_assignment_by_type(client, assignment_id, options)


def references_export_analysis_manifest(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("output"):
        raise ValueError("references export-analysis-manifest requires --output <accepted-manifest.json>.")
    if not options.get("corpus-key"):
        raise ValueError("references export-analysis-manifest requires --corpus-key <key>.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    payload = build_reference_analysis_manifest(
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        references=references,
        attachments=attachments,
    )
    _write_json_file(options["output"], payload)
    print(
        f"references\texport-analysis-manifest\t{corpus_id}\t{options['output']}\t{len(payload['items'])} accepted"
    )


def references_export_scope_training(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("output"):
        raise ValueError("references export-scope-training requires --output <scope-training.json>.")
    if not options.get("corpus-key"):
        raise ValueError("references export-scope-training requires --corpus-key <key>.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    payload = build_reference_scope_training_export(
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        references=references,
        attachments=attachments,
    )
    _write_json_file(options["output"], payload)
    print(
        f"references\texport-scope-training\t{corpus_id}\t{options['output']}\t"
        f"{payload['counts']['positive']} positive\t{payload['counts']['negative']} negative"
    )


def _require_reference_process_runtime(command_name: str) -> None:
    runtime_role = str(os.environ.get("PAPYRUS_RUNTIME_ROLE") or "").strip().lower()
    if runtime_role and runtime_role not in {"cli", "worker"}:
        raise RuntimeError(
            f"{command_name} requires utility worker runtime with reachable GROBID service/container. "
            f"Current PAPYRUS_RUNTIME_ROLE={runtime_role!r} is not supported."
        )
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        raise RuntimeError(
            f"{command_name} requires utility worker runtime with reachable GROBID service/container. "
            "API/Lambda runtime is not supported for process commands."
        )


def extract_last_json_object(text: str) -> dict[str, Any] | None:
    for line in reversed(text.strip().splitlines()):
        value = line.strip()
        if not value.startswith("{") or not value.endswith("}"):
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _write_json_file(path: str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_reference_status_filter(value: Any) -> str:
    status = str(value or "all").strip().lower()
    allowed = {"all", "pending", "accepted", "rejected", "archived"}
    if status not in allowed:
        raise ValueError(f"--status must be one of {', '.join(sorted(allowed))}.")
    return status
