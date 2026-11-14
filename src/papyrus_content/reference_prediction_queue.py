"""One Cyclotron prediction for a Reference that was created without one (PPY-eac36e).

Only the monitoring router (``monitoring_router.deliver_reference``) and the by-hand ``references decide-relevance`` sweep used to record a relevance
decision. A Reference an editor pasted into the console, one a catalog import created, one chat created, one a research packet registered: none of
them had a prediction, and the References page and the public pages show nothing for a pending Reference until it has one.

The site's Cyclotron is a hosted service that only the monitoring router can reach (it signs with the router's role). The code that creates a Reference
does not run there, so it asks the router, through the lane the editor-selected email imports already use (docs/monitoring-cloud.md, "Predictions for
editor-selected newsletter References"): one row in the monitoring table's own partition, on the existing sparse ``routing`` index. The router's
``email-references`` task drains it, decides through the same path as a monitor's item (enrichment, one ``decide`` per binding, polling), and records the
decision with the same builders ``deliver_reference`` uses. No new table, no new index, no new schedule.

The request is made once, by the event that creates the Reference. Nothing scans a corpus to find References that lack a prediction. A request is
idempotent: its row id derives from the publication, the corpus and the Reference, and the router drops a request for a Reference that already has a
prediction (a finite ``predictedAcceptProbability``, as the public pages define it) without calling the Cyclotron.

The same request row also asks for the Reference's enrichment (``predictFor.enrich``): the router captures the text, writes the summary
(and GROBID fields for a paper) and copies the curation onto the Reference BEFORE it decides, "enrich before decide" as a monitor's item does. One row,
one key, so a retry of the creation never duplicates either half. ``enrichment_source_id`` keys the separate, enrich-only row the by-hand
``references queue-enrichment`` backfill writes for a Reference whose prediction row is already settled (``predictFor.enrichOnly``): it decides nothing.

A request that cannot be made is reported by its caller (``PredictionRequest.error``), never swallowed: the Reference exists and stays hidden until
it has a prediction. A request the router could not complete keeps its row in the lane and is retried with backoff; one it must refuse ends with its
reason on the ROUTE row and in the router's log and receipt.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from .reference_intake_validation import IntakeError, canonical_source_url

LANE = "reference-predictions"
SOURCE_TYPE = "reference"
REFERENCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
MUTATION = "mutation MonitoringQueueReferencePredictions($input: AWSJSON!) { monitoringQueueReferencePredictions(input: $input) }"


def prediction_source_id(endpoint: str, corpus_id: str, reference_id: str) -> str:
    """The request's stable identity (also the Cyclotron item id suffix): one per publication, corpus and Reference."""
    return sha256(f"reference-prediction\n{endpoint}\n{corpus_id}\n{reference_id}".encode()).hexdigest()


def enrichment_source_id(endpoint: str, corpus_id: str, reference_id: str) -> str:
    """The identity of an enrich-only request (the backfill's): one per publication, corpus and Reference, and never equal to ``prediction_source_id``,
    so a settled prediction row does not hide a Reference that still needs its enrichment."""
    return sha256(f"reference-enrichment\n{endpoint}\n{corpus_id}\n{reference_id}".encode()).hexdigest()


def wants_enrichment(disc: dict[str, Any] | None) -> bool:
    """True for a request that asks the router to enrich the Reference first (every request made since this was added; an older queued one does not)."""
    return is_prediction_request(disc) and bool(disc["predictFor"].get("enrich") or disc["predictFor"].get("enrichOnly"))


def is_enrich_only(disc: dict[str, Any] | None) -> bool:
    return is_prediction_request(disc) and bool(disc["predictFor"].get("enrichOnly"))


def is_prediction_request(disc: dict[str, Any] | None) -> bool:
    return bool(disc) and disc.get("sourceType") == SOURCE_TYPE and isinstance(disc.get("predictFor"), dict)


def has_real_prediction(reference: dict[str, Any]) -> bool:
    """A real prediction is a finite ``predictedAcceptProbability`` on the row, the definition the public pages use (home_page/export.stored_prediction).
    ``predictionDecidedAt`` and ``predictionSortKey`` are not evidence: a row with a time but no number is still hidden."""
    value = reference.get("predictedAcceptProbability")
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


has_prediction = has_real_prediction


def queue_reference_predictions(store, *, endpoint: str, references: list[dict[str, Any]], subject: str, now: str | None = None) -> dict[str, Any]:
    """Queue one prediction request per Reference. ``references`` are ``{"referenceId", "sourceUri", "title"}``.

    Raises ``IntakeError`` when the publication has no live Cyclotron decisions (nothing is queued, so the caller says so). A request already queued
    (or already settled) is left exactly as it is. Returns ``{"queued", "alreadyQueued", "sourceIds"}``.
    """
    from .monitoring import SourceItem
    from .monitoring_router import gsi_partition, validate_router_config

    if not isinstance(references, list) or not references:
        raise IntakeError("Name at least one Reference to predict.")
    raw = store.get("CONFIG#router")
    if not raw:
        raise IntakeError("Cloud predictions are not configured for this monitor.")
    config = validate_router_config(raw)
    publication = next((row for row in config["publications"] if row["appsyncEndpoint"].rstrip("/") == str(endpoint).rstrip("/")), None)
    if publication is None:
        raise IntakeError("This publication is not served by the cloud Cyclotron router.")
    if not config["enabled"] or config["mode"] != "live" or config["decisions"] != "cyclotron":
        raise IntakeError("Cloud predictions are not enabled for this publication.")
    monitor_id = store.pk.removeprefix("MONITOR#")
    stamp = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    queued, already, source_ids = 0, 0, []
    for reference in references:
        reference_id = reference.get("referenceId") if isinstance(reference, dict) else None
        if not isinstance(reference_id, str) or not REFERENCE_ID.fullmatch(reference_id):
            raise IntakeError("A Reference id is required for each prediction.")
        source = canonical_source_url(reference.get("sourceUri"))
        title = str(reference.get("title") or source).strip()[:1000] or source
        enrich_only = bool(reference.get("enrichOnly"))
        source_id = (enrichment_source_id if enrich_only else prediction_source_id)(endpoint, publication["corpusId"], reference_id)
        item = SourceItem(source_id, title, source, source, None)
        disc = {"pk": store.pk, "sk": f"DISC#{source_id}#000001", "monitorId": monitor_id, "sourceType": SOURCE_TYPE, "sourceId": source_id,
                "title": title, "canonicalUrl": source, "sourceItemUrl": source, "sourceUrl": source, "fingerprint": item.fingerprint, "revision": 1,
                "observedAt": stamp, "eventId": f"reference-prediction-{source_id}", "runId": f"reference-prediction-{source_id[:16]}",
                "routing": "collected", "predictFor": {"subject": subject, "publicationId": publication["publicationId"], "referenceId": reference_id, "enrich": True,
                               **({"enrichOnly": True} if enrich_only else {})},
                "gsi1pk": gsi_partition(monitor_id, LANE), "gsi1sk": f"{stamp}#{source_id}#000001"}
        try:
            store.table.put_item(Item=disc, ConditionExpression="attribute_not_exists(pk)")
            queued += 1
        except Exception as error:   # noqa: BLE001 - only the conditional-check failure means "already there"
            if "ConditionalCheckFailed" not in str(error) and getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            already += 1
        source_ids.append(source_id)
    return {"queued": queued, "alreadyQueued": already, "sourceIds": source_ids}


@dataclass
class PredictionRequest:
    """What a route reports about asking for predictions. ``error`` is set when the request could not be made; the Reference still exists and stays hidden."""
    requested: int = 0
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_json(self) -> dict[str, Any]:
        return {"requested": self.requested, "ok": self.ok, **({"error": self.error} if self.error else {}), **self.detail}


def request_predictions_through_appsync(client, references: list[dict[str, Any]]) -> PredictionRequest:
    """For a route that runs as a signed-in editor (the CLI, chat): ask the site to queue the predictions. Never raises; a failure is the result's ``error``."""
    wanted = [reference for reference in references if reference.get("referenceId") and reference.get("sourceUri")]
    if not wanted:
        return PredictionRequest()
    try:
        answer = client.graphql(MUTATION, {"input": json.dumps({"references": wanted})}).get("monitoringQueueReferencePredictions")
        answer = json.loads(answer) if isinstance(answer, str) else answer
        if not isinstance(answer, dict) or answer.get("error"):
            message = (answer or {}).get("message") or (answer or {}).get("error") or "no answer"
            return PredictionRequest(error=" ".join(str(message).split())[:300])
        return PredictionRequest(requested=int(answer.get("queued", 0)) + int(answer.get("alreadyQueued", 0)), detail={k: answer[k] for k in ("queued", "alreadyQueued") if k in answer})
    except Exception as error:   # noqa: BLE001 - the Reference is already created; the caller reports this
        return PredictionRequest(error=" ".join(f"{type(error).__name__}: {error}".split())[:300])


def request_predictions(client, references: list[dict[str, Any]], *, env=None) -> PredictionRequest:
    """For a route that runs on an operator's machine or as a chat agent: ask for the predictions by the transport that route can reach.

    A signed-in editor (the CLI's user-session mode) asks the site, which queues them (``monitoringQueueReferencePredictions``). An operator with AWS
    credentials writes the request rows into the monitoring table itself. A route with neither is told so in ``error``. Never raises."""
    import os

    from .user_auth_mode import user_auth_requested

    env = os.environ if env is None else env
    if not references:
        return PredictionRequest()
    try:
        if user_auth_requested():
            return request_predictions_through_appsync(client, references)
        from .monitoring_view import default_email_store_factory
        store = default_email_store_factory(env)()
        if store is None:
            raise IntakeError("the monitoring table is not reachable from here")
        done = queue_reference_predictions(store, endpoint=str(getattr(client, "endpoint", "") or env.get("PAPYRUS_GRAPHQL_ENDPOINT") or "").rstrip("/"),
                                           references=references, subject="operator")
        return PredictionRequest(requested=done["queued"] + done["alreadyQueued"], detail={k: done[k] for k in ("queued", "alreadyQueued")})
    except Exception as error:   # noqa: BLE001 - the Reference exists; the caller reports this
        return PredictionRequest(error=" ".join(f"{type(error).__name__}: {error}".split())[:300])


def references_for_prediction(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The request items for created or matched Reference rows: current, with an address, and not already predicted.

    Pending or already voted: a Reference an import created accepted, or one an editor accepted before its prediction arrived, still needs one, because the
    site's Cyclotron learns from votes only on a Reference it has predicted (the feedback pass reads the decision's delivery row)."""
    out = []
    for row in rows:
        if not row or row.get("versionState", "current") != "current":
            continue
        if row.get("reusedExisting") or has_prediction(row) or not row.get("sourceUri") or not row.get("id"):
            continue
        out.append({"referenceId": row["id"], "sourceUri": row["sourceUri"], "title": row.get("title") or row["sourceUri"]})
    return out


def references_for_enrichment(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The enrich-only request items (the by-hand backfill) for current, unarchived Reference rows whose content is not captured in full."""
    from .reference_capture_state import normalize_capture_state
    out = []
    for row in rows:
        if not row or row.get("versionState", "current") != "current" or row.get("curationStatus") == "archived":
            continue
        if not row.get("sourceUri") or not row.get("id") or normalize_capture_state(row.get("captureState")) in ("full", "running"):
            continue
        out.append({"referenceId": row["id"], "sourceUri": row["sourceUri"], "title": row.get("title") or row["sourceUri"], "enrichOnly": True})
    return out


def videos_needing_local_run(rows: list[dict[str, Any]]) -> int:
    """How many of these Reference rows (or request items) are the address of one video. The cloud cannot read a video platform's thumbnail or transcript
    (they refuse cloud addresses), so each of these waits for the local runners (``references capture-transcripts`` and ``capture-thumbnails``)."""
    from .reference_medium import MEDIUM_VIDEO, medium_of
    return sum(1 for row in rows if medium_of(row.get("sourceUri")) == MEDIUM_VIDEO)


def video_line(prefix: str, count: int) -> str | None:
    """The one line a creating command prints so nobody has to guess that a video still needs a run on a machine YouTube answers."""
    if not count:
        return None
    noun = "video needs" if count == 1 else "videos need"
    return (f"{prefix}\tvideos\t{count}\t{count} {noun} a local run: papyrus references capture-thumbnails --write "
            f"and papyrus references capture-transcripts (the cloud cannot read a video platform's picture or transcript)")


#: An unpredicted Reference sorts at exactly this score on the prediction index (reference_feed_keys), so reading highest first can stop below it.
UNPREDICTED_SORT_KEY = "0.500000"


def unpredicted_rows(client, corpus_id: str):
    """For the by-hand backfill: the rows of a corpus's prediction index (``<corpus>#unrated`` and ``<corpus>#rated``) from the highest score down to 0.5,
    which is where an unpredicted row sorts. Nothing below 0.5 is read and no other partition is touched; the caller keeps the rows with no number."""
    for partition in ("unrated", "rated"):
        for row in client.iterate_newest_first("referencesByFeedStateAndPrediction", f"{corpus_id}#{partition}"):
            if str(row.get("predictionSortKey") or "") < UNPREDICTED_SORT_KEY:
                break
            yield row


def feed_rows(client, corpus_id: str):
    """For the by-hand enrichment backfill: every row of a corpus's feed index (``<corpus>#unrated`` and ``<corpus>#rated``), one partition page at a time.
    No other partition is touched and no table is scanned; the caller keeps the rows whose content is not captured."""
    for partition in ("unrated", "rated"):
        yield from client.iterate_newest_first("referencesByFeedStateAndPrediction", f"{corpus_id}#{partition}")


def references_created_by(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The prediction items for the References a record-change plan created (an update is a Reference that already existed and is not re-requested)."""
    return references_for_prediction([change["expected"] for change in changes if change.get("modelName") == "Reference" and change.get("action") == "create"])


def request_for_created(client, changes: list[dict[str, Any]], prefix: str) -> PredictionRequest | None:
    """For a command that just applied a record-change plan: request a prediction for each Reference it created and print the one line saying how that went."""
    wanted = references_created_by(changes)
    if not wanted:
        return None
    request = request_predictions(client, wanted)
    print(request_line(prefix, request), flush=True)
    line = video_line(prefix, videos_needing_local_run(wanted))
    if line:
        print(line, flush=True)
    return request


def request_line(prefix: str, request: PredictionRequest) -> str:
    """The one tab-separated line a command prints about a prediction request; a failure says what to do about it."""
    if request.ok:
        return f"{prefix}\tprediction\trequested\t{request.requested}"
    return (f"{prefix}\tprediction\tNOT-REQUESTED\t{request.error}\tthe new References stay hidden until they have a prediction; "
            f"queue them with `papyrus references queue-predictions` once the cause is fixed")


def queue_after_intake(result: dict[str, Any], arguments: dict[str, Any], *, env=None, store=None) -> dict[str, Any]:
    """For the Lambda that creates the Reference (console intake, and the CLI's user-session intake, which calls the same action): queue the
    predictions straight into the monitoring table. Never raises; the answer rides on the action's response as ``prediction`` and a failure is also logged,
    so the person who pasted the address is told that the Reference will stay hidden until someone asks again."""
    import os

    env = os.environ if env is None else env
    titles = {}
    for item in (arguments.get("items") or []):
        try:
            titles[canonical_source_url(item.get("source_uri"))] = item.get("title")
        except Exception:   # noqa: BLE001 - validated by intake already; a bad item has no Reference here
            continue
    rows = [{**row, "title": titles.get(row.get("sourceUri")) or row.get("sourceUri")} for row in result.get("references") or []]
    wanted = references_for_prediction(rows)
    if not wanted:
        return PredictionRequest().to_json()
    try:
        if store is None:
            from .monitoring_view import default_email_store_factory
            store = default_email_store_factory(env)()
        if store is None:
            raise IntakeError("Cloud predictions are not configured for this publication.")
        endpoint = (env.get("PAPYRUS_GRAPHQL_ENDPOINT") or "").rstrip("/")
        done = queue_reference_predictions(store, endpoint=endpoint, references=wanted, subject="user-intake")
        return PredictionRequest(requested=done["queued"] + done["alreadyQueued"], detail={**{k: done[k] for k in ("queued", "alreadyQueued")},
                                 "videos": videos_needing_local_run(wanted)}).to_json()   # the CLI says how many of these wait for a local run
    except Exception as error:   # noqa: BLE001 - the Reference exists; say plainly that its prediction was not requested
        message = " ".join(f"{error}".split())[:300]
        print(json.dumps({"referencePrediction": "queue_failed", "references": len(wanted), "reason": message}))
        return PredictionRequest(error=message, detail={"references": len(wanted)}).to_json()
