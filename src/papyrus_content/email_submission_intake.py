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
from email.utils import getaddresses
from hashlib import sha256

from .email_submission import (
    LINK_BATCH_SIZE,
    MAX_MESSAGE_BYTES,
    SubmissionRejected,
    extract_submission,
)
from .email_submission_authorization import (
    EditorLookupUnavailable,
    publication_ids_for_editor,
)
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
    if any(not row.get("userPoolId") for row in router["publications"]):
        raise ConfigurationError("email_editor_directory_required")
    if router["feedback"]:
        raise ConfigurationError("email_feedback_must_be_disabled")
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
    """Keep bounded SES receipt statuses and derived policy failures, never raw headers."""
    if record.get("eventSource") != "aws:ses":
        return {"provenance": "unverified-event", "verdicts": {name: "UNAVAILABLE" for name in SES_VERDICTS},
                "failedGateCodes": ["ses_event_source_untrusted"]}
    ses = record.get("ses") or {}
    receipt = ses.get("receipt") or {}
    verdicts = {}
    for name, field in SES_VERDICTS.items():
        raw = receipt.get(field)
        status = raw.get("status") if isinstance(raw, dict) else None
        verdicts[name] = status if isinstance(status, str) and SES_VERDICT_STATUS.fullmatch(status) else "UNAVAILABLE"

    failed = []
    for name in ("spam", "virus", "dmarc"):
        if verdicts[name] != "PASS":
            failed.append(f"{name}_verdict_not_passed")
    if verdicts["spf"] != "PASS" and verdicts["dkim"] != "PASS":
        failed.append("spf_or_dkim_verdict_not_passed")
    return {
        "provenance": "ses-invocation-receipt",
        "verdicts": verdicts,
        "failedGateCodes": failed,
    }


class EmailStore(DynamoStore):
    """All access stays in one configured MONITOR partition."""

    def get(self, monitor_id, sk):
        return self._get(monitor_id, sk)

    def put(self, monitor_id, record):
        self.table.put_item(Item={**record, "pk": pk(monitor_id)})

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
    # These verdicts come from SES's invocation payload, never Authentication-Results
    # in an untrusted MIME object. DMARC PASS supplies From-domain alignment.
    verdicts = _ses_diagnostics(record)["verdicts"]
    if (not all(verdicts[name] == "PASS" for name in ("spam", "virus", "dmarc"))
            or not (verdicts["spf"] == "PASS" or verdicts["dkim"] == "PASS")):
        raise SubmissionRejected("sender_authentication_failed")
    try:
        recipients = _addresses(mail.get("destination"), 10)
        matched = _addresses(receipt.get("recipients"), 10)
    except ConfigurationError as error:
        raise SubmissionRejected("envelope_recipients_invalid") from error
    if not set(matched) <= set(recipients) or not set(recipients) <= set(config["addresses"]):
        raise SubmissionRejected("destination_scope_mismatch")
    headers = mail.get("commonHeaders") or {}
    from_values = headers.get("from")
    if not isinstance(from_values, list) or len(from_values) != 1 or not isinstance(from_values[0], str):
        raise SubmissionRejected("sender_invalid")
    senders = getaddresses(from_values)
    try:
        sender = _address(senders[0][1]) if len(senders) == 1 else ""
    except ConfigurationError as error:
        raise SubmissionRejected("sender_invalid") from error
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


def _discovery(monitor_id, config, row, receipt_key, message_id, link, source_url, authorized_publications):
    source_id = sha256(f"{message_id}\n{link['url']}".encode()).hexdigest()
    item = SourceItem(source_id, link["title"] or link["url"], link["url"], link["url"], None)
    provenance = {key: row[key] for key in ("sesMessageId", "sender", "recipients", "subject", "rfcMessageId",
                                           "s3Bucket", "s3Key", "mimeSha256", "accountId", "observedAt")}
    provenance.update(receiptId=receipt_key, destinationKind=config["kind"], inputTrust="untrusted-source-material")
    return {"pk": pk(monitor_id), "sk": f"DISC#{source_id}#000001", "monitorId": monitor_id,
            "sourceType": "email", "sourceId": source_id, "title": item.title,
            "canonicalUrl": item.canonical_url, "sourceItemUrl": item.source_item_url,
            "fingerprint": item.fingerprint, "revision": 1, "observedAt": row["observedAt"],
            "eventId": _digest([monitor_id, source_id, item.fingerprint]), "sourceUrl": source_url,
            "runId": receipt_key, "routing": "collected", "emailProvenance": provenance,
            "emailRoutingFingerprint": config["routingFingerprint"],
            "emailAuthorizedPublicationIds": authorized_publications,
            "gsi1pk": f"ROUTING#{monitor_id}#collected",
            "gsi1sk": f"{row['observedAt']}#{source_id}#000001"}


def _drain_manifest(store, s3, monitor_id, config, row, receipt_key, message_id, authorized_publications):
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
            store.put_discovery(monitor_id, _discovery(
                monitor_id, config, row, receipt_key, message_id, link, source_url, authorized_publications))
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


def process_ses_record(record, store, *, monitor_id, bucket, prefix="email-submissions/", s3, cognito, now=None):
    """Process one authenticated SES delivery; expected refusals are durable receipts.

    Infrastructure failures are recorded and raised for Lambda retries/DLQ.
    Discoveries are immutable conditional writes; interrupted batches resume safely.
    """
    now = time.time() if now is None else now
    if (not MONITOR_ID.fullmatch(monitor_id or "") or not bucket or not prefix
            or not prefix.endswith("/") or prefix.startswith("/") or ".." in prefix
            or prefix == "inbound-email/"):
        raise ConfigurationError("email_runtime_binding_invalid")
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
        if row and row.get("status") in {"queued", "rejected"}:
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
        if "sesDiagnostics" not in row:
            row["sesDiagnostics"] = diagnostics
        if row["s3Bucket"] != bucket or row["s3Key"] != key:
            raise ConfigurationError("email_retry_object_changed")
        stage = "destination_configuration"
        row.update(status="processing", processingStage=stage, updatedAt=_iso(now))
        store.put(monitor_id, row)
        if not config["enabled"]:
            raise SubmissionRejected("email_destination_disabled")
        stage = "ses_authentication"
        row["processingStage"] = stage
        sender, recipients = _trusted_envelope(record, config)
        row.update(sender=sender, recipients=recipients)
        # Charge authenticated but unauthorized senders to the same per-address
        # ceiling so directory lookups cannot be used as an unbounded oracle.
        stage = "sender_rate_limit"
        row["processingStage"] = stage
        store.reserve_rate(monitor_id, sender, message_id, row["firstSeen"], config["maxMessagesPerSenderHour"])
        stage = "editor_membership"
        row["processingStage"] = stage
        try:
            authorized_publications = publication_ids_for_editor(sender, config["publications"], cognito)
        except EditorLookupUnavailable as error:
            raise RuntimeError("editor_membership_lookup_unavailable") from error
        authorized_publications = sorted(set(authorized_publications) & set(config["publicationIds"]))
        if row and row.get("emailAuthorizedPublicationIds") is not None:
            authorized_publications = sorted(set(authorized_publications)
                                             & set(row["emailAuthorizedPublicationIds"]))
        if not authorized_publications:
            raise SubmissionRejected("sender_not_active_editor")
        stage = "mime_read"
        row["processingStage"] = stage
        raw = _mime(s3, bucket, key, config["maxMessageBytes"])
        digest = sha256(raw).hexdigest()
        if row.get("mimeSha256") and row["mimeSha256"] != digest:
            raise SubmissionRejected("email_mime_changed")
        stage = "mime_parse"
        row["processingStage"] = stage
        parsed = extract_submission(raw)
        if parsed["sender"] != sender:
            raise SubmissionRejected("mime_sender_mismatch")
        if not parsed["links"]:
            raise SubmissionRejected("no_editorial_links")
        stage = "discovery_queue"
        row["processingStage"] = stage
        row.update(mimeSha256=digest, subject=parsed["subject"], rfcMessageId=parsed["messageId"],
                   warnings=parsed["warnings"], linkCount=len(parsed["links"]),
                   destinationFingerprint=config["destinationFingerprint"],
                   emailAuthorizedPublicationIds=authorized_publications,
                   excludedLinkCount=parsed.get("excludedLinkCount", 0))
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
        result = _drain_manifest(store, s3, monitor_id, config, row, receipt_key, message_id, authorized_publications)
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
            current = publication_ids_for_editor(row["sender"], config["publications"], cognito)
            authorized = sorted(set(current) & set(config["publicationIds"])
                                & set(row.get("emailAuthorizedPublicationIds", current)))
            if not authorized:
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
                                           row["sesMessageId"], authorized))
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
        result = _resume_pending(EmailStore(table), monitor_id, os.environ["EMAIL_RAW_BUCKET"],
                                 s3, cognito)
        print(json.dumps(result))
        return result
    records = event.get("Records") if isinstance(event, dict) else None
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise SubmissionRejected("one_ses_record_required")
    result = process_ses_record(records[0], EmailStore(table), monitor_id=monitor_id,
                                bucket=os.environ["EMAIL_RAW_BUCKET"],
                                prefix=os.environ.get("EMAIL_RAW_PREFIX", "email-submissions/"), s3=s3,
                                cognito=cognito)
    print(json.dumps(result))  # safe status codes and hashed receipt id, never raw email/body/sender
    return result
