"""Trusted SES envelope -> bounded MIME links -> the existing discovery queue.

The SES receipt rule invokes this collector after storing MIME. Its IAM resource
policy, not an email header, establishes the event's authority. This collector
has no source-fetch, model, AppSync, feedback-mail or console-agent capability.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from decimal import Decimal
from hashlib import sha256

from .email_submission import (
    LINK_BATCH_SIZE,
    MAX_MESSAGE_BYTES,
    SubmissionRejected,
    extract_submission,
)
from .email_fingerprint import content_fingerprint, group_key, member_key
from .email_quarantine import LEGACY_REJECTION_CODES, QUARANTINE_STATUS, RECEIPT_ID, inherit_group_decision
from .monitoring import SourceItem, _digest, _iso
from .monitoring_cloud import ConditionFailed, DynamoStore, pk
from .monitoring_router import email_routing_fingerprint, validate_router_config

EMAIL_CONFIG_SK = "CONFIG#email"
LOCK_SK = "LOCK#email"
LOCK_SECONDS = 180  # longer than the receiver Lambda's 120-second timeout
RECEIPT_SECONDS = 30 * 86400
RESUME_BATCH_SECONDS = 60
MANIFEST_READ_BYTES = 128 * 1024
MONITOR_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SES_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
ADDRESS = re.compile(r"^[^\s@<>*,;]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$")
SES_VERDICTS = {
    "spam": "spamVerdict",
    "virus": "virusVerdict",
    "spf": "spfVerdict",
    "dkim": "dkimVerdict",
    "dmarc": "dmarcVerdict",
}
SES_VERDICT_STATUS = re.compile(r"^(?:PASS|FAIL|GRAY|PROCESSING_FAILED|PERMERROR|NEUTRAL|NONE)$")
EMAIL_DETAIL_CHUNK_BYTES = 180 * 1024


class ConfigurationError(ValueError):
    """Operator configuration is absent or unsafe; never silently skip it."""


class IntakeBusy(RuntimeError):
    """A concurrent invocation owns the short lease; let Lambda retry later."""


def _address(value):
    if not isinstance(value, str) or len(value) > 254 or not ADDRESS.fullmatch(value.lower()):
        raise ConfigurationError("email_address_invalid")
    return value.lower()


def _addresses(values, maximum):
    if not isinstance(values, list) or not 1 <= len(values) <= maximum:
        raise ConfigurationError("email_address_list_invalid")
    result = [_address(value) for value in values]
    if len(result) != len(set(result)):
        raise ConfigurationError("email_addresses_duplicated")
    return result


def _limit(raw, name, default, maximum):
    value = raw.get(name, default)
    # DynamoDB numbers arrive as Decimal; reject fractional/bool/string values.
    if (isinstance(value, (bool, str)) or not isinstance(value, (int, float, Decimal))
            or int(value) != value or not 1 <= value <= maximum):
        raise ConfigurationError(f"{name}_invalid")
    return int(value)


def validate_email_config(raw, raw_router):
    if not isinstance(raw, dict) or not isinstance(raw_router, dict):
        raise ConfigurationError("email_and_router_configuration_required")
    allowed = {"pk", "sk", "schemaVersion", "enabled", "accountId", "kind", "addresses",
               "publicationIds", "maxMessageBytes", "maxLinks", "maxMessagesPerSenderHour"}
    if set(raw) - allowed or raw.get("schemaVersion") != 1 or type(raw.get("enabled")) is not bool:
        raise ConfigurationError("email_configuration_shape_invalid")
    account = raw.get("accountId")
    if not isinstance(account, str) or not account.strip() or len(account) > 128:
        raise ConfigurationError("email_account_required")
    try:
        router = validate_router_config(raw_router)
    except (ValueError, TypeError, KeyError) as error:
        raise ConfigurationError("email_router_configuration_invalid") from error
    if router.get("accountId") != account:
        raise ConfigurationError("email_router_account_mismatch")
    publications = raw.get("publicationIds")
    if (not isinstance(publications, list) or not publications or len(publications) > 25
            or any(not isinstance(value, str) for value in publications)
            or len(set(publications)) != len(publications)
            or set(publications) != {row["publicationId"] for row in router["publications"]}):
        raise ConfigurationError("email_publication_grants_mismatch")
    if any(row["procedureTriggers"] for row in router["publications"]):
        raise ConfigurationError("email_does_not_execute_procedures")
    kind = raw.get("kind")
    if kind == "publication":
        if len(publications) != 1 or router["decisions"] != "direct":
            raise ConfigurationError("email_publication_destination_requires_one_direct_route")
    elif kind == "shared":
        cyclotron = router.get("cyclotron") or {}
        if (router["decisions"] != "cyclotron" or cyclotron.get("accountId") != account
                or not cyclotron.get("runId") or not cyclotron.get("roleArn")):
            raise ConfigurationError("email_shared_destination_requires_account_bound_cyclotron")
    else:
        raise ConfigurationError("email_destination_kind_invalid")
    addresses = _addresses(raw.get("addresses"), 10)
    destination_fingerprint = _digest([account, kind, sorted(addresses), sorted(publications)])
    return {"enabled": raw["enabled"], "accountId": account, "kind": kind,
            "addresses": addresses,
            "publicationIds": publications,
            "maxMessageBytes": _limit(raw, "maxMessageBytes", MAX_MESSAGE_BYTES, MAX_MESSAGE_BYTES),
            "maxMessagesPerSenderHour": _limit(raw, "maxMessagesPerSenderHour", 10, 100),
            "routingFingerprint": email_routing_fingerprint(router),
            "destinationFingerprint": destination_fingerprint, "publications": router["publications"]}


def _ses_diagnostics(record):
    """Keep SES auth outcomes as untrusted signals; only spam/virus are safety gates."""
    if record.get("eventSource") != "aws:ses":
        return {"provenance": "unverified-event", "verdicts": {name: "UNAVAILABLE" for name in SES_VERDICTS},
                "warnings": [], "blockedGateCodes": ["ses_event_source_untrusted"]}
    ses = record.get("ses") or {}
    receipt = ses.get("receipt") or {}
    verdicts = {}
    for name, field in SES_VERDICTS.items():
        raw = receipt.get(field)
        status = raw.get("status") if isinstance(raw, dict) else None
        verdicts[name] = status if isinstance(status, str) and SES_VERDICT_STATUS.fullmatch(status) else "UNAVAILABLE"

    warnings = [f"{name}_not_passed" for name in ("spf", "dkim", "dmarc")
                if verdicts[name] != "PASS"]
    blocked = [f"{name}_verdict_not_passed" for name in ("spam", "virus") if verdicts[name] != "PASS"]
    return {
        "provenance": "ses-invocation-receipt-untrusted-auth-signals",
        "verdicts": verdicts,
        "warnings": warnings,
        "blockedGateCodes": blocked,
    }


class EmailStore(DynamoStore):
    """All access stays in one configured MONITOR partition."""

    def get(self, monitor_id, sk):
        return self._get(monitor_id, sk)

    def put(self, monitor_id, record):
        self.table.put_item(Item={**record, "pk": pk(monitor_id)})

    def put_email_detail_chunks(self, monitor_id, receipt_key, body, links, ttl):
        digest = receipt_key.removeprefix("EMAIL#")
        encoded = body.encode("utf-8")
        chunks, start = [], 0
        while start < len(encoded):
            end = min(start + EMAIL_DETAIL_CHUNK_BYTES, len(encoded))
            while end < len(encoded) and encoded[end] & 0xC0 == 0x80:
                end -= 1
            chunks.append(encoded[start:end].decode("utf-8"))
            start = end
        for index, chunk in enumerate(chunks or [""]):
            self.put(monitor_id, {"sk": f"EMAILDETAIL#{digest}#BODY#{index:04d}", "text": chunk, "ttl": ttl})
        batch, batch_size, index = [], 2, 0
        for link in links:
            link_size = len(json.dumps(link, ensure_ascii=True, separators=(",", ":")).encode("ascii")) + 1
            if batch and batch_size + link_size > EMAIL_DETAIL_CHUNK_BYTES:
                self.put(monitor_id, {"sk": f"EMAILDETAIL#{digest}#LINKS#{index:04d}",
                                      "json": json.dumps(batch, ensure_ascii=True, separators=(",", ":")), "ttl": ttl})
                index += 1
                batch, batch_size = [], 2
            batch.append(link)
            batch_size += link_size
        if batch:
            self.put(monitor_id, {"sk": f"EMAILDETAIL#{digest}#LINKS#{index:04d}",
                                  "json": json.dumps(batch, ensure_ascii=True, separators=(",", ":")), "ttl": ttl})

    def acquire_email_lock(self, monitor_id, owner, now):
        try:
            self._conditional_put({"pk": pk(monitor_id), "sk": LOCK_SK, "owner": owner,
                                   "expiresAt": int(now + LOCK_SECONDS)},
                                  "attribute_not_exists(pk) OR expiresAt < :now", {":now": int(now)})
            return True
        except ConditionFailed:
            return False

    def release_email_lock(self, monitor_id, owner):
        try:
            self.table.delete_item(Key={"pk": pk(monitor_id), "sk": LOCK_SK},
                                   ConditionExpression="#o = :owner",
                                   ExpressionAttributeNames={"#o": "owner"},
                                   ExpressionAttributeValues={":owner": owner})
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise

    def pending_receipts(self, monitor_id, limit=10):
        from boto3.dynamodb.conditions import Key

        response = self.table.query(IndexName="routing", KeyConditionExpression=Key("gsi1pk").eq(
            f"EMAIL_PENDING#{monitor_id}"), Limit=limit, ScanIndexForward=True)
        return [self._clean(row) for row in response.get("Items", [])]

    def prefixed(self, monitor_id, prefix):
        """Every row of one partition whose sort key starts with `prefix`, in key order."""
        rows, start = [], None
        while True:
            extra = {"ExclusiveStartKey": start} if start else {}
            response = self.table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={":pk": pk(monitor_id), ":prefix": prefix}, ScanIndexForward=True, **extra)
            rows.extend(self._clean(row) for row in response.get("Items", []))
            start = response.get("LastEvaluatedKey")
            if not start:
                return rows

    def email_links(self, monitor_id, receipt_key):
        """The candidate links an editor reviewed, exactly as stored at quarantine time."""
        links = []
        for row in self.prefixed(monitor_id, f"EMAILDETAIL#{receipt_key.removeprefix('EMAIL#')}#LINKS#"):
            chunk = json.loads(row.get("json", "[]"))
            if not isinstance(chunk, list) or any(not isinstance(link, dict) for link in chunk):
                raise RuntimeError("email_quarantine_links_corrupt")
            links.extend(chunk)
        return links

    def pending_decisions(self, monitor_id, limit=25):
        from boto3.dynamodb.conditions import Key

        response = self.table.query(IndexName="routing", KeyConditionExpression=Key("gsi1pk").eq(
            f"EMAIL_ACTION#{monitor_id}"), Limit=limit, ScanIndexForward=True)
        return [self._clean(row) for row in response.get("Items", [])]

    def reserve_rate(self, monitor_id, sender, message_id, first_seen, maximum):
        """A bounded set makes retrying the same SES delivery consume one slot."""
        hour = int(first_seen // 3600)
        key = f"RATE#{hour}#{sha256(sender.encode()).hexdigest()}"
        row = self.get(monitor_id, key) or {"sk": key, "messages": [], "ttl": (hour + 48) * 3600}
        if message_id in row["messages"]:
            return
        if len(row["messages"]) >= maximum:
            raise SubmissionRejected("sender_rate_limit")
        row["messages"].append(message_id)
        self.put(monitor_id, row)


def _trusted_envelope(record, config):
    ses = record.get("ses") or {}
    mail, receipt = ses.get("mail") or {}, ses.get("receipt") or {}
    if record.get("eventSource") != "aws:ses":
        raise SubmissionRejected("ses_event_required")
    # SPF/DKIM/DMARC are recorded as untrusted signals, not an intake prerequisite.
    # Spam and virus checks remain hard safety gates, and MIME headers grant no authority.
    verdicts = _ses_diagnostics(record)["verdicts"]
    for name in ("spam", "virus"):
        if verdicts[name] != "PASS":
            raise SubmissionRejected(f"{name}_verdict_not_passed")
    try:
        recipients = _addresses(mail.get("destination"), 10)
        matched = _addresses(receipt.get("recipients"), 10)
    except ConfigurationError as error:
        raise SubmissionRejected("envelope_recipients_invalid") from error
    if not set(matched) <= set(recipients) or not set(recipients) <= set(config["addresses"]):
        raise SubmissionRejected("destination_scope_mismatch")
    # The SES envelope source is only an untrusted rate-limit key/provenance value.
    # It is never compared to Cognito and never grants authority. Empty/invalid
    # senders share one bucket rather than bypassing the configured rate ceiling.
    source = mail.get("source")
    sender = source.lower() if isinstance(source, str) and ADDRESS.fullmatch(source.lower()) else "unknown"
    return sender, sorted(recipients)


def _mime(s3, bucket, key, limit):
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    try:
        if response.get("ContentLength", limit + 1) > limit:
            raise SubmissionRejected("message_too_large")
        raw = body.read(limit + 1)
    finally:
        body.close()
    if len(raw) > limit:
        raise SubmissionRejected("message_too_large")
    return raw


def _manifest_key(receipt_key):
    return "email-submissions/manifests/" + receipt_key.removeprefix("EMAIL#") + ".jsonl"


def _manifest_bytes(links):
    return b"".join((json.dumps(link, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
                   for link in links)


def _manifest_batch(s3, bucket, key, cursor, size, digest):
    """Read one bounded range; return links paired with their ending byte offsets."""
    if cursor >= size:
        return []
    end = min(size, cursor + MANIFEST_READ_BYTES)
    response = s3.get_object(Bucket=bucket, Key=key, Range=f"bytes={cursor}-{end - 1}")
    if (response.get("Metadata") or {}).get("sha256") != digest:
        raise RuntimeError("email_manifest_digest_mismatch")
    body = response["Body"]
    try:
        data = body.read(MANIFEST_READ_BYTES + 1)
    finally:
        body.close()
    if len(data) > MANIFEST_READ_BYTES:
        raise RuntimeError("email_manifest_read_bound_exceeded")
    lines, position = [], cursor
    for line in data.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break
        if lines and len(lines) >= LINK_BATCH_SIZE:
            break
        try:
            item = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            raise RuntimeError("email_manifest_corrupt") from None
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            raise TypeError("email_manifest_corrupt")
        position += len(line)
        lines.append((item, position))
        if len(lines) >= LINK_BATCH_SIZE:
            break
    if not lines and cursor < size:
        # Every URL/title record is well below this fixed range because extraction
        # enforces MAX_URL_LENGTH and MAX_TITLE_LENGTH.
        raise RuntimeError("email_manifest_line_invalid")
    return lines


LINK_EXPLORATION_SECONDS = 30  # one link's whole exploration, well inside the resume batch and the lock

# Installed by handler(); None (no network) everywhere else, so extraction and tests never explore.
link_explorer = None


def explore_email_link(link, row):
    """Follow one subscriber-specific wrapper to its article, or find the article by its headline (link_exploration).

    Returns the exploration; its destination is only ever the canonical public address that passes the editorial-address check.
    """
    from .email_submission import safe_editorial_url
    from .link_exploration import Context, explore

    return explore(link["url"], Context(title=link.get("title") or "", sender=row.get("headerFrom") or ""),
                   want_text=False, accept=safe_editorial_url, deadline_seconds=LINK_EXPLORATION_SECONDS)


def install_link_explorer(environ=None):
    """Turn exploration on for the deployed intake unless EMAIL_LINK_EXPLORATION=off."""
    global link_explorer
    link_explorer = None if (environ or os.environ).get("EMAIL_LINK_EXPLORATION", "on").strip().lower() == "off" else explore_email_link


def _explored(link, row):
    """The resolved link for an unresolved wrapper, or None. Records the typed reason when it cannot be resolved."""
    if link_explorer is None:
        return None
    result = link_explorer(link, row)
    if not result.ok:
        reasons = row.setdefault("unresolvedReasons", {})
        reasons[result.failure] = int(reasons.get(result.failure, 0)) + 1
        return None
    title = link.get("title") or ""
    # Anchor-less links were titled with their own address: never carry the subscriber-specific wrapper into a title.
    found = {"url": result.url, "title": result.url if not title or link["url"] in title or title.startswith(("http://", "https://")) else title}
    if result.via == "search" and result.search:
        # DynamoDB takes Decimal, not float.
        found["linkExploration"] = json.loads(json.dumps({"foundVia": "search", **result.search.as_dict()}), parse_float=Decimal)
    row["exploredLinkCount"] = int(row.get("exploredLinkCount", 0)) + 1
    return found


def _discovery(monitor_id, config, row, receipt_key, message_id, link, source_url, destination_publications):
    source_id = sha256(f"{message_id}\n{link['url']}".encode()).hexdigest()
    item = SourceItem(source_id, link["title"] or link["url"], link["url"], link["url"], None)
    provenance = {key: row[key] for key in ("sesMessageId", "sender", "recipients", "subject", "rfcMessageId",
                                           "s3Bucket", "s3Key", "mimeSha256", "accountId", "observedAt")}
    provenance.update(receiptId=receipt_key, destinationKind=config["kind"], inputTrust="untrusted-source-material",
                      trustMode="data-only", sesDiagnostics=row["sesDiagnostics"])
    if link.get("linkExploration"):
        provenance["linkExploration"] = link["linkExploration"]  # found via search: the query and match score, never a subscriber link
    return {"pk": pk(monitor_id), "sk": f"DISC#{source_id}#000001", "monitorId": monitor_id,
            "sourceType": "email", "sourceId": source_id, "title": item.title,
            "canonicalUrl": item.canonical_url, "sourceItemUrl": item.source_item_url,
            "fingerprint": item.fingerprint, "revision": 1, "observedAt": row["observedAt"],
            "eventId": _digest([monitor_id, source_id, item.fingerprint]), "sourceUrl": source_url,
            "runId": receipt_key, "routing": "collected", "emailProvenance": provenance,
            "emailRoutingFingerprint": config["routingFingerprint"],
            "emailTrustMode": "data-only",
            "emailDestinationPublicationIds": destination_publications,
            "gsi1pk": f"ROUTING#{monitor_id}#collected",
            "gsi1sk": f"{row['observedAt']}#{source_id}#000001"}


def _note_candidate(store, monitor_id, discovery):
    """The shared candidate for this URL (docs/search-monitors.md), so web monitors skip what an email already brought.
    Best effort: it never fails the intake."""
    try:
        from .monitoring_candidates import record_candidate
        record_candidate(store, url=discovery["canonicalUrl"], title=discovery["title"], published_at=None, monitor_id=monitor_id,
                         source_type="email", group=monitor_id, source_id=discovery["sourceId"], found_at=discovery["observedAt"],
                         run_id=discovery["runId"], collected=True)
    except Exception as error:   # noqa: BLE001
        print(json.dumps({"email": "candidate_failed", "monitorId": monitor_id, "error": str(error)[:200]}))


def _drain_manifest(store, s3, monitor_id, config, row, receipt_key, message_id, destination_publications):
    cursor, size = int(row.get("cursorBytes", 0)), int(row["manifestBytes"])
    source_url = "mailto:" + config["addresses"][0]
    deadline = time.monotonic() + RESUME_BATCH_SECONDS
    processed = int(row.get("processedCount", 0))
    if cursor < size:
        links = _manifest_batch(s3, row["s3Bucket"], row["manifestKey"], cursor, size,
                                row["manifestSha256"])
        if not links:
            raise RuntimeError("email_manifest_cursor_stalled")
        for link, next_cursor in links:
            if time.monotonic() >= deadline:
                break
            if link.get("resolutionStatus") == "unresolved":
                link = _explored(link, row)
            if link is not None:
                discovery = _discovery(monitor_id, config, row, receipt_key, message_id, link, source_url, destination_publications)
                store.put_discovery(monitor_id, discovery)
                _note_candidate(store, monitor_id, discovery)
            cursor = next_cursor
            processed += 1
    done = cursor >= size
    row.update(cursorBytes=cursor, processedCount=processed, updatedAt=_iso(time.time()))
    # The checkpoint counts records consumed, not successful conditional puts: a
    # replay after a crash can safely encounter discoveries already routed onward.
    if done:
        row.update(status="queued", processingStage="queued", errorCode=None,
                   sectionHandoff="pending-reference-site-sweep")
        row.pop("gsi1pk", None)
        row.pop("gsi1sk", None)
    else:
        row.update(status="processing", processingStage="discovery_queue", errorCode=None,
                   gsi1pk=f"EMAIL_PENDING#{monitor_id}",
                   gsi1sk=f"{row['observedAt']}#{receipt_key}")
    store.put(monitor_id, row)
    return {"status": row["status"], "receiptId": receipt_key, "linkCount": row["linkCount"],
            "processedCount": row.get("processedCount", 0), "cursorBytes": cursor}


def _check_runtime_binding(monitor_id, bucket, prefix):
    if (not MONITOR_ID.fullmatch(monitor_id or "") or not bucket or not prefix
            or not prefix.endswith("/") or prefix.startswith("/") or ".." in prefix
            or prefix == "inbound-email/"):
        raise ConfigurationError("email_runtime_binding_invalid")


def _store_details(store, monitor_id, receipt_key, row, parsed):
    """Private, expiring, inert rendering and candidate links for editor review."""
    detail_body = parsed.get("safeBodyText", "")
    store.put_email_detail_chunks(monitor_id, receipt_key, detail_body, parsed["links"], row["ttl"])
    row["safeBodyBytes"] = len(detail_body.encode("utf-8"))
    row["safeBodyChunks"] = max(1, (row["safeBodyBytes"] + EMAIL_DETAIL_CHUNK_BYTES - 1) // EMAIL_DETAIL_CHUNK_BYTES)
    row["unresolvedLinkCount"] = sum(link.get("resolutionStatus") == "unresolved" for link in parsed["links"])
    row["contentFingerprint"] = content_fingerprint(parsed["subject"], parsed["links"], detail_body)


def _write_index(store, monitor_id, config, row, receipt_key):
    """The newest-first list row and, for grouping, this copy's membership of its fingerprint group."""
    digest = receipt_key.removeprefix("EMAIL#")
    store.put(monitor_id, {"sk": f"EMAILINDEX#{row['observedAt']}#{digest}",
                           "receiptId": receipt_key, "destinationPublicationIds": config["publicationIds"],
                           "ttl": row["ttl"]})
    if row.get("contentFingerprint"):
        store.put(monitor_id, {"sk": member_key(row["contentFingerprint"], receipt_key), "receiptId": receipt_key,
                               "observedAt": row["observedAt"], "ttl": row["ttl"]})


def _hold_for_review(store, monitor_id, config, row, receipt_key, parsed, now=None, group=None):
    row.update(status=QUARANTINE_STATUS, processingStage="pending_review",
               reviewRequired=True, pendingReviewLinkCount=len(parsed["links"]),
               processedCount=0, updatedAt=_iso(time.time() if now is None else now))
    row.pop("gsi1pk", None)
    row.pop("gsi1sk", None)
    store.put(monitor_id, row)
    _write_index(store, monitor_id, config, row, receipt_key)
    group = group or store.get(monitor_id, group_key(row["contentFingerprint"]))
    if group:
        # The group was already decided: this copy takes that decision (the receiver applies it) and no one is asked again.
        inherit_group_decision(store, monitor_id, group, row)
    return {"status": QUARANTINE_STATUS, "receiptId": receipt_key,
            "linkCount": row["linkCount"], "processedCount": 0}


def process_ses_record(record, store, *, monitor_id, bucket, prefix="email-submissions/", s3, cognito, now=None):
    """Process one authenticated SES delivery; expected refusals are durable receipts.

    Infrastructure failures are recorded and raised for Lambda retries/DLQ.
    Discoveries are immutable conditional writes; interrupted batches resume safely.
    """
    now = time.time() if now is None else now
    _check_runtime_binding(monitor_id, bucket, prefix)
    message_id = ((record.get("ses") or {}).get("mail") or {}).get("messageId")
    if not isinstance(message_id, str) or not SES_ID.fullmatch(message_id):
        raise SubmissionRejected("ses_message_id_invalid")
    key = prefix + message_id
    receipt_key = "EMAIL#" + sha256(message_id.encode()).hexdigest()
    owner = uuid.uuid4().hex
    if not store.acquire_email_lock(monitor_id, owner, now):
        raise IntakeBusy("email_intake_busy")
    row = None
    stage = "configuration"
    try:
        config = validate_email_config(store.get(monitor_id, EMAIL_CONFIG_SK), store.get(monitor_id, "CONFIG#router"))
        row = store.get(monitor_id, receipt_key)
        if row and (row.get("status") in {"queued", "pending_review", "discarded"} or row.get("releasedAt")):
            return {"status": "duplicate", "previousStatus": row["status"], "receiptId": receipt_key}
        if row and row.get("status") == "rejected":
            # Replay only the former authentication/membership refusals when SES
            # malware/spam checks were already clean. Other terminal failures remain
            # terminal; the same message ID and discovery keys make this idempotent.
            diagnostics = row.get("sesDiagnostics") or {}
            verdicts = diagnostics.get("verdicts") or {}
            replayable = (row.get("errorCode") in {"sender_authentication_failed", "sender_not_active_editor"}
                          and verdicts.get("spam") == "PASS" and verdicts.get("virus") == "PASS")
            if not replayable:
                return {"status": "duplicate", "previousStatus": row["status"], "receiptId": receipt_key}
        if row and (row.get("routingFingerprint") != config["routingFingerprint"]
                    or row.get("manifestKey") and row.get("destinationFingerprint") != config["destinationFingerprint"]):
            raise ConfigurationError("email_retry_binding_changed")
        diagnostics = _ses_diagnostics(record)
        row = row or {"sk": receipt_key, "sesMessageId": message_id, "firstSeen": int(now),
                      "observedAt": _iso(now), "s3Bucket": bucket, "s3Key": key,
                      "accountId": config["accountId"], "routingFingerprint": config["routingFingerprint"],
                      "destinationFingerprint": config["destinationFingerprint"],
                      "sesDiagnostics": diagnostics,
                      "ttl": int(now + RECEIPT_SECONDS)}
        # On explicitly replayable historical auth/membership refusals, replace stale
        # diagnostics with the current SES receipt's bounded per-verdict signals.
        row["sesDiagnostics"] = diagnostics
        if row["s3Bucket"] != bucket or row["s3Key"] != key:
            raise ConfigurationError("email_retry_object_changed")
        stage = "destination_configuration"
        row.update(status="processing", processingStage=stage, updatedAt=_iso(now))
        store.put(monitor_id, row)
        if not config["enabled"]:
            raise SubmissionRejected("email_destination_disabled")
        stage = "ses_safety_checks"
        row["processingStage"] = stage
        sender, recipients = _trusted_envelope(record, config)
        row.update(sender=sender, recipients=recipients)
        # This is abuse backpressure only. The untrusted envelope source never
        # grants editorial membership or selects a destination.
        stage = "sender_rate_limit"
        row["processingStage"] = stage
        store.reserve_rate(monitor_id, sender, message_id, row["firstSeen"], config["maxMessagesPerSenderHour"])
        stage = "mime_read"
        row["processingStage"] = stage
        raw = _mime(s3, bucket, key, config["maxMessageBytes"])
        digest = sha256(raw).hexdigest()
        if row.get("mimeSha256") and row["mimeSha256"] != digest:
            raise SubmissionRejected("email_mime_changed")
        stage = "mime_parse"
        row["processingStage"] = stage
        parsed = extract_submission(raw)
        stage = "discovery_queue"
        row["processingStage"] = stage
        warnings = set(parsed["warnings"])
        if diagnostics["warnings"]:
            warnings.add("ses_authentication_unverified")
        row.update(mimeSha256=digest, subject=parsed["subject"], rfcMessageId=parsed["messageId"],
                   headerFrom=parsed["sender"], warnings=sorted(warnings), linkCount=len(parsed["links"]),
                   destinationFingerprint=config["destinationFingerprint"],
                   emailTrustMode="data-only", emailDestinationPublicationIds=config["publicationIds"],
                   excludedLinkCount=parsed.get("excludedLinkCount", 0))
        _store_details(store, monitor_id, receipt_key, row, parsed)
        group = store.get(monitor_id, group_key(row["contentFingerprint"]))
        if diagnostics["warnings"] or (group and group.get("decision") == "discard"):
            # Authentication failures are quarantined: visible to editors as inert text
            # with the extracted links, but never routed until an editor accepts them.
            # A copy of an email whose group was rejected is held only to be closed by that decision.
            return _hold_for_review(store, monitor_id, config, row, receipt_key, parsed, group=group)
        if not row.get("manifestKey"):
            manifest = _manifest_bytes(parsed["links"])
            manifest_key = _manifest_key(receipt_key)
            s3.put_object(Bucket=bucket, Key=manifest_key, Body=manifest,
                          ContentType="application/x-ndjson", ServerSideEncryption="AES256",
                          Metadata={"sha256": sha256(manifest).hexdigest()})
            row.update(manifestKey=manifest_key, manifestSha256=sha256(manifest).hexdigest(),
                       manifestBytes=len(manifest), cursorBytes=0, processedCount=0)
        row.update(gsi1pk=f"EMAIL_PENDING#{monitor_id}", gsi1sk=f"{row['observedAt']}#{receipt_key}")
        store.put(monitor_id, row)
        _write_index(store, monitor_id, config, row, receipt_key)
        result = _drain_manifest(store, s3, monitor_id, config, row, receipt_key, message_id,
                                 config["publicationIds"])
        return result
    except SubmissionRejected as error:
        if row is None:
            row = {"sk": receipt_key, "sesMessageId": message_id, "ttl": int(now + RECEIPT_SECONDS)}
        row.update(status="rejected", processingStage=stage, errorCode=error.code, updatedAt=_iso(now))
        row.pop("gsi1pk", None)
        row.pop("gsi1sk", None)
        store.put(monitor_id, row)
        return {"status": "rejected", "receiptId": receipt_key, "reason": error.code}
    except Exception:
        if row is not None:
            row.update(status="failed", processingStage=stage, errorCode="intake_dependency_failed",
                       updatedAt=_iso(now))
            # A manifest-backed checkpoint remains discoverable by the resume sweep.
            if row.get("manifestKey"):
                row.update(gsi1pk=f"EMAIL_PENDING#{monitor_id}", gsi1sk=f"{row['observedAt']}#{receipt_key}")
            store.put(monitor_id, row)
        raise
    finally:
        store.release_email_lock(monitor_id, owner)


LEGACY_VERDICTS = {name: "UNAVAILABLE" for name in SES_VERDICTS}


def quarantine_legacy_receipt(store, s3, *, monitor_id, bucket, prefix="email-submissions/", receipt_key, now=None):
    """Move one receipt refused by the earlier authentication gate into quarantine.

    The earlier gate refused before parsing the MIME, so the receipt has no stored text or
    links and no per-check verdicts. The private MIME is still in the 30-day prefix: read it
    once through the normal bounded parser, store the inert text and links for editor review,
    and hold the receipt as `pending_review`. Existing receipt fields are kept. Nothing is
    routed; the message waits for an editor's Accept or Reject like any other held message.
    """
    now = time.time() if now is None else now
    _check_runtime_binding(monitor_id, bucket, prefix)
    if not isinstance(receipt_key, str) or not RECEIPT_ID.fullmatch(receipt_key):
        raise ConfigurationError("email_receipt_id_invalid")
    owner = uuid.uuid4().hex
    if not store.acquire_email_lock(monitor_id, owner, now):
        raise IntakeBusy("email_intake_busy")
    try:
        config = validate_email_config(store.get(monitor_id, EMAIL_CONFIG_SK), store.get(monitor_id, "CONFIG#router"))
        row = store.get(monitor_id, receipt_key)
        if row is None:
            return {"status": "not_found", "receiptId": receipt_key}
        if row.get("status") != "rejected" or row.get("errorCode") not in LEGACY_REJECTION_CODES:
            return {"status": "unchanged", "previousStatus": row.get("status"), "receiptId": receipt_key}
        ttl = row.get("ttl")
        if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= now:
            return {"status": "expired", "receiptId": receipt_key}
        diagnostics = row.get("sesDiagnostics") if isinstance(row.get("sesDiagnostics"), dict) else None
        verdicts = (diagnostics or {}).get("verdicts") or {}
        if any(verdicts.get(name, "PASS") != "PASS" for name in ("spam", "virus")):
            return {"status": "unchanged", "reason": "safety_verdict_not_passed", "receiptId": receipt_key}
        message_id = row.get("sesMessageId")
        if not isinstance(message_id, str) or not SES_ID.fullmatch(message_id) or \
                "EMAIL#" + sha256(message_id.encode()).hexdigest() != receipt_key:
            raise ConfigurationError("email_receipt_message_id_invalid")
        key = prefix + message_id
        if row.get("s3Bucket", bucket) != bucket or row.get("s3Key", key) != key:
            raise ConfigurationError("email_retry_object_changed")
        raw = _mime(s3, bucket, key, config["maxMessageBytes"])
        parsed = extract_submission(raw)
        observed = row.get("observedAt") or _iso(row.get("firstSeen", now))
        row.update(
            legacyErrorCode=row["errorCode"], errorCode=None, observedAt=observed, s3Bucket=bucket, s3Key=key,
            accountId=config["accountId"], routingFingerprint=config["routingFingerprint"],
            destinationFingerprint=config["destinationFingerprint"], sender=row.get("sender", "unknown"),
            recipients=row.get("recipients", []),  # not recorded by the earlier gate; never inferred
            sesDiagnostics=diagnostics or {"provenance": "legacy-receipt-no-verdict-snapshot",
                                           "verdicts": dict(LEGACY_VERDICTS), "warnings": [], "blockedGateCodes": []},
            mimeSha256=sha256(raw).hexdigest(), subject=parsed["subject"], rfcMessageId=parsed["messageId"],
            headerFrom=parsed["sender"], warnings=sorted(set(parsed["warnings"]) | {"legacy_authentication_rejection"}),
            linkCount=len(parsed["links"]), emailTrustMode="data-only",
            emailDestinationPublicationIds=config["publicationIds"],
            excludedLinkCount=parsed.get("excludedLinkCount", 0))
        _store_details(store, monitor_id, receipt_key, row, parsed)
        return _hold_for_review(store, monitor_id, config, row, receipt_key, parsed, now)
    except SubmissionRejected as error:
        # Unparseable or oversized mail stays refused; editors are never shown unsafe content.
        return {"status": "unchanged", "reason": error.code, "receiptId": receipt_key}
    finally:
        store.release_email_lock(monitor_id, owner)


def quarantine_legacy_receipts(store, s3, *, monitor_id, bucket, prefix="email-submissions/", receipt_keys=None, now=None):
    """Quarantine the named receipts, or every legacy-refused receipt when none are named."""
    if receipt_keys is None:
        receipt_keys = [row["sk"] for row in store.prefixed(monitor_id, "EMAIL#")
                        if row.get("status") == "rejected" and row.get("errorCode") in LEGACY_REJECTION_CODES]
    return [quarantine_legacy_receipt(store, s3, monitor_id=monitor_id, bucket=bucket, prefix=prefix,
                                      receipt_key=key, now=now) for key in receipt_keys]


def backfill_fingerprints(store, *, monitor_id, now=None):
    """One-off: give receipts stored before grouping a content fingerprint and group membership.

    Data-preserving. Reads each receipt's stored inert text and candidate links (the same inputs
    intake fingerprints), adds only ``contentFingerprint`` and the ``EMAILFP#`` membership row, and
    leaves every other field untouched. A receipt that was already decided seeds its group's decision
    so later copies inherit it. Idempotent; receipts without stored details are skipped.
    """
    now = time.time() if now is None else now
    owner = uuid.uuid4().hex
    if not store.acquire_email_lock(monitor_id, owner, now):
        raise IntakeBusy("email_intake_busy")
    counts = {"fingerprinted": 0, "alreadyFingerprinted": 0, "skipped": 0, "groupsSeeded": 0}
    try:
        for row in store.prefixed(monitor_id, "EMAIL#"):
            key = row.get("sk")
            if not isinstance(key, str) or not RECEIPT_ID.fullmatch(key) or row.get("emailTrustMode") != "data-only":
                counts["skipped"] += 1
                continue
            if row.get("contentFingerprint"):
                counts["alreadyFingerprinted"] += 1
                fingerprint = row["contentFingerprint"]
            else:
                digest = key.removeprefix("EMAIL#")
                details = store.prefixed(monitor_id, f"EMAILDETAIL#{digest}#")
                if not details and not row.get("subject"):
                    counts["skipped"] += 1
                    continue
                body = "".join(item.get("text", "") for item in details if "#BODY#" in item["sk"])
                fingerprint = content_fingerprint(row.get("subject"), store.email_links(monitor_id, key), body)
                store.put(monitor_id, {**row, "contentFingerprint": fingerprint})
                counts["fingerprinted"] += 1
            if isinstance(row.get("ttl"), int) and row["ttl"] > now:
                store.put(monitor_id, {"sk": member_key(fingerprint, key), "receiptId": key,
                                       "observedAt": row.get("observedAt"), "ttl": row["ttl"]})
            decision = row.get("decision") if isinstance(row.get("decision"), dict) else None
            if (decision and decision.get("decision") in {"release", "discard"} and decision.get("requestedAt")
                    and not store.get(monitor_id, group_key(fingerprint))):
                seed = {"sk": group_key(fingerprint), "fingerprint": fingerprint, "ttl": row.get("ttl"),
                        **{k: decision[k] for k in ("decision", "actor", "actorEmail", "reason", "requestedAt",
                                                    "publicationId") if k in decision}}
                if seed["ttl"] is None:
                    del seed["ttl"]
                if "actor" in seed and "publicationId" in seed:
                    store.put(monitor_id, seed)
                    counts["groupsSeeded"] += 1
        return {"status": "fingerprint-backfilled", **counts}
    finally:
        store.release_email_lock(monitor_id, owner)


def _finish_decision(store, monitor_id, action, outcome, now):
    store.put(monitor_id, {**{k: v for k, v in action.items() if k not in {"gsi1pk", "gsi1sk"}},
                           "outcome": outcome, "appliedAt": _iso(now)})
    return {"status": outcome, "receiptId": action["receiptId"], "decision": action["decision"]}


def _apply_decision(store, s3, monitor_id, bucket, action, now):
    """Apply one recorded editor decision to its receipt. Idempotent; the receipt's only writer."""
    receipt_key = action.get("receiptId")
    if (not isinstance(receipt_key, str) or not RECEIPT_ID.fullmatch(receipt_key)
            or action.get("decision") not in {"release", "discard"}):
        return _finish_decision(store, monitor_id, action, "decision_invalid", now)
    row = store.get(monitor_id, receipt_key)
    if row is None:
        return _finish_decision(store, monitor_id, action, "receipt_missing", now)
    record = {key: action[key] for key in ("decision", "actor", "actorEmail", "reason", "requestedAt", "publicationId",
                                        "groupFingerprint")
              if key in action}
    record["appliedAt"] = _iso(now)
    if action["decision"] == "discard":
        if row.get("status") == "pending_review":
            row.update(status="discarded", processingStage="discarded", reviewRequired=False,
                       decision=record, discardedAt=_iso(now), updatedAt=_iso(now))
            row.pop("gsi1pk", None)
            row.pop("gsi1sk", None)
            store.put(monitor_id, row)
        elif row.get("status") != "discarded":
            return _finish_decision(store, monitor_id, action, "not_quarantined", now)
        return _finish_decision(store, monitor_id, action, "discarded", now)
    if row.get("releasedAt"):
        return _finish_decision(store, monitor_id, action, "released", now)
    if row.get("status") != "pending_review":
        return _finish_decision(store, monitor_id, action, "not_quarantined", now)
    ttl = row.get("ttl")
    if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= now:
        return _finish_decision(store, monitor_id, action, "expired", now)
    config = validate_email_config(store.get(monitor_id, EMAIL_CONFIG_SK), store.get(monitor_id, "CONFIG#router"))
    if not config["enabled"]:
        raise RuntimeError("email_destination_disabled")  # retried on the next sweep, never dropped
    if (row.get("routingFingerprint") != config["routingFingerprint"]
            or row.get("destinationFingerprint") != config["destinationFingerprint"]):
        return _finish_decision(store, monitor_id, action, "email_retry_binding_changed", now)
    if not set(row.get("emailDestinationPublicationIds", [])) & set(config["publicationIds"]):
        return _finish_decision(store, monitor_id, action, "email_destination_scope_empty", now)
    links = store.email_links(monitor_id, receipt_key)
    if int(row.get("linkCount") or 0) and not links:
        return _finish_decision(store, monitor_id, action, "quarantine_details_missing", now)
    row.update(releasedAt=_iso(now), decision=record, reviewRequired=False, errorCode=None, updatedAt=_iso(now))
    if links:
        manifest = _manifest_bytes(links)
        manifest_key = _manifest_key(receipt_key)
        s3.put_object(Bucket=bucket, Key=manifest_key, Body=manifest,
                      ContentType="application/x-ndjson", ServerSideEncryption="AES256",
                      Metadata={"sha256": sha256(manifest).hexdigest()})
        row.update(manifestKey=manifest_key, manifestSha256=sha256(manifest).hexdigest(),
                   manifestBytes=len(manifest), cursorBytes=0, processedCount=0, status="processing",
                   processingStage="release_queue", gsi1pk=f"EMAIL_PENDING#{monitor_id}",
                   gsi1sk=f"{row['observedAt']}#{receipt_key}")
    else:
        row.update(status="queued", processingStage="queued", processedCount=0,
                   sectionHandoff="pending-reference-site-sweep")
    store.put(monitor_id, row)  # the existing resume sweep drains the manifest into discoveries
    return _finish_decision(store, monitor_id, action, "released", now)


def apply_pending_decisions(store, s3, *, monitor_id, bucket, now=None, batch=25):
    """Apply recorded editor decisions. A busy lease or dependency failure leaves them pending."""
    now = time.time() if now is None else now
    results = []
    for action in store.pending_decisions(monitor_id, batch):
        owner = uuid.uuid4().hex
        if not store.acquire_email_lock(monitor_id, owner, now):
            break
        try:
            results.append(_apply_decision(store, s3, monitor_id, bucket, action, now))
        except Exception as error:
            print(json.dumps({"decisionRetry": type(error).__name__, "receiptId": action.get("receiptId")}))
            results.append({"status": "retry", "receiptId": action.get("receiptId")})
        finally:
            store.release_email_lock(monitor_id, owner)
    return results


def _resume_pending(store, monitor_id, bucket, s3, cognito, *, now=None, limit=1):
    now = time.time() if now is None else now
    results = []
    for row in store.pending_receipts(monitor_id, limit=limit):
        receipt_key = row.get("sk")
        owner = uuid.uuid4().hex
        if not store.acquire_email_lock(monitor_id, owner, now):
            continue
        stage = "receipt_load"
        try:
            row = store.get(monitor_id, receipt_key)
            if not row or row.get("gsi1pk") != f"EMAIL_PENDING#{monitor_id}":
                continue
            stage = "destination_configuration"
            config = validate_email_config(store.get(monitor_id, EMAIL_CONFIG_SK),
                                           store.get(monitor_id, "CONFIG#router"))
            if not config["enabled"]:
                continue
            if (row.get("routingFingerprint") != config["routingFingerprint"]
                    or row.get("destinationFingerprint") != config["destinationFingerprint"]
                    or not set(row.get("recipients", [])) <= set(config["addresses"])):
                row.update(status="failed", processingStage=stage,
                           errorCode="email_retry_binding_changed", updatedAt=_iso(now))
                row.pop("gsi1pk", None)
                row.pop("gsi1sk", None)
                store.put(monitor_id, row)
                results.append({"status": "failed", "receiptId": receipt_key,
                                "reason": "email_retry_binding_changed"})
                continue
            stage = "editor_membership"
            if row.get("emailTrustMode") == "data-only":
                destination_publications = sorted(set(row.get("emailDestinationPublicationIds", []))
                                                   & set(config["publicationIds"]))
                if not destination_publications:
                    row.update(status="failed", processingStage=stage,
                               errorCode="email_destination_scope_empty", updatedAt=_iso(now))
                    row.pop("gsi1pk", None)
                    row.pop("gsi1sk", None)
                    store.put(monitor_id, row)
                    results.append({"status": "failed", "receiptId": receipt_key,
                                    "reason": "email_destination_scope_empty"})
                    continue
            else:
                # Compatibility for already queued receipts created by the earlier
                # editor-gated implementation. New intake is destination-scoped.
                from .email_submission_authorization import (
                    EditorLookupUnavailable,
                    publication_ids_for_editor,
                )
                try:
                    current = publication_ids_for_editor(row["sender"], config["publications"], cognito)
                except (EditorLookupUnavailable, KeyError) as error:
                    raise RuntimeError("editor_membership_lookup_unavailable") from error
                destination_publications = sorted(set(current) & set(config["publicationIds"])
                                                  & set(row.get("emailAuthorizedPublicationIds", current)))
                if not destination_publications:
                    row.update(status="rejected", processingStage=stage,
                               errorCode="sender_not_active_editor", updatedAt=_iso(now))
                    row.pop("gsi1pk", None)
                    row.pop("gsi1sk", None)
                    store.put(monitor_id, row)
                    results.append({"status": "rejected", "receiptId": receipt_key,
                                    "reason": "sender_not_active_editor"})
                    continue
            stage = "manifest_resume"
            if (row.get("s3Bucket") != bucket or row.get("manifestKey") != _manifest_key(receipt_key)
                    or int(row.get("manifestBytes", 0)) <= 0):
                raise RuntimeError("email_manifest_binding_invalid")
            row.update(status="processing", processingStage=stage, updatedAt=_iso(now))
            store.put(monitor_id, row)
            results.append(_drain_manifest(store, s3, monitor_id, config, row, receipt_key,
                                           row["sesMessageId"], destination_publications))
        except Exception:
            row.update(status="failed", processingStage=stage,
                       errorCode="intake_dependency_failed", updatedAt=_iso(now),
                       gsi1pk=f"EMAIL_PENDING#{monitor_id}",
                       gsi1sk=f"{row['observedAt']}#{receipt_key}")
            store.put(monitor_id, row)
            raise
        finally:
            store.release_email_lock(monitor_id, owner)
    return {"status": "resumed", "receipts": results}


def handler(event, context):
    """SES receipt and private manifest-resume schedule entry point."""
    import boto3

    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    s3 = boto3.client("s3")
    cognito = boto3.client("cognito-idp")
    monitor_id = os.environ["EMAIL_MONITOR_ID"]
    if isinstance(event, dict) and event.get("task") == "resume":
        if event.get("monitorId") != monitor_id:
            raise ConfigurationError("email_resume_monitor_mismatch")
        install_link_explorer()
        store, bucket = EmailStore(table), os.environ["EMAIL_RAW_BUCKET"]
        decisions = apply_pending_decisions(store, s3, monitor_id=monitor_id, bucket=bucket)
        result = _resume_pending(store, monitor_id, bucket, s3, cognito)
        result["decisions"] = decisions
        print(json.dumps(result))
        return result
    if isinstance(event, dict) and event.get("task") == "fingerprint-backfill":
        # Operator task: fingerprint receipts stored before duplicate grouping existed.
        if event.get("monitorId") != monitor_id:
            raise ConfigurationError("email_fingerprint_monitor_mismatch")
        result = backfill_fingerprints(EmailStore(table), monitor_id=monitor_id)
        print(json.dumps(result))
        return result
    if isinstance(event, dict) and event.get("task") == "quarantine-legacy":
        # Operator task: hold receipts refused by the earlier authentication gate for editor review.
        if event.get("monitorId") != monitor_id:
            raise ConfigurationError("email_quarantine_monitor_mismatch")
        result = {"status": "quarantined", "receipts": quarantine_legacy_receipts(
            EmailStore(table), s3, monitor_id=monitor_id, bucket=os.environ["EMAIL_RAW_BUCKET"],
            prefix=os.environ.get("EMAIL_RAW_PREFIX", "email-submissions/"), receipt_keys=event.get("receiptIds"))}
        print(json.dumps(result))
        return result
    records = event.get("Records") if isinstance(event, dict) else None
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise SubmissionRejected("one_ses_record_required")
    install_link_explorer()
    result = process_ses_record(records[0], EmailStore(table), monitor_id=monitor_id,
                                bucket=os.environ["EMAIL_RAW_BUCKET"],
                                prefix=os.environ.get("EMAIL_RAW_PREFIX", "email-submissions/"), s3=s3,
                                cognito=cognito)
    print(json.dumps(result))  # safe status codes and hashed receipt id, never raw email/body/sender
    return result
