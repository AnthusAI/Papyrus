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
    MAX_LINKS,
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
MONITOR_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SES_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
ADDRESS = re.compile(r"^[^\s@<>*,;]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$")


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
    return {"enabled": raw["enabled"], "accountId": account, "kind": kind,
            "addresses": _addresses(raw.get("addresses"), 10),
            "publicationIds": publications,
            "maxMessageBytes": _limit(raw, "maxMessageBytes", MAX_MESSAGE_BYTES, MAX_MESSAGE_BYTES),
            "maxLinks": _limit(raw, "maxLinks", MAX_LINKS, MAX_LINKS),
            "maxMessagesPerSenderHour": _limit(raw, "maxMessagesPerSenderHour", 10, 100),
            "routingFingerprint": email_routing_fingerprint(router), "publications": router["publications"]}


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
    passed = lambda name: (receipt.get(name) or {}).get("status") == "PASS"
    if (not all(passed(name) for name in ("spamVerdict", "virusVerdict", "dmarcVerdict"))
            or not (passed("spfVerdict") or passed("dkimVerdict"))):
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
    try:
        config = validate_email_config(store.get(monitor_id, EMAIL_CONFIG_SK), store.get(monitor_id, "CONFIG#router"))
        row = store.get(monitor_id, receipt_key)
        if row and row.get("status") in {"queued", "rejected"}:
            return {"status": "duplicate", "previousStatus": row["status"], "receiptId": receipt_key}
        if row and row.get("routingFingerprint") != config["routingFingerprint"]:
            raise ConfigurationError("email_retry_binding_changed")
        row = row or {"sk": receipt_key, "sesMessageId": message_id, "firstSeen": int(now),
                      "observedAt": _iso(now), "s3Bucket": bucket, "s3Key": key,
                      "accountId": config["accountId"], "routingFingerprint": config["routingFingerprint"],
                      "ttl": int(now + RECEIPT_SECONDS)}
        if row["s3Bucket"] != bucket or row["s3Key"] != key:
            raise ConfigurationError("email_retry_object_changed")
        row.update(status="processing", updatedAt=_iso(now))
        store.put(monitor_id, row)
        if not config["enabled"]:
            raise SubmissionRejected("email_destination_disabled")
        sender, recipients = _trusted_envelope(record, config)
        row.update(sender=sender, recipients=recipients)
        # Charge authenticated but unauthorized senders to the same per-address
        # ceiling so directory lookups cannot be used as an unbounded oracle.
        store.reserve_rate(monitor_id, sender, message_id, row["firstSeen"], config["maxMessagesPerSenderHour"])
        try:
            authorized_publications = publication_ids_for_editor(sender, config["publications"], cognito)
        except EditorLookupUnavailable as error:
            raise RuntimeError("editor_membership_lookup_unavailable") from error
        authorized_publications = sorted(set(authorized_publications) & set(config["publicationIds"]))
        if not authorized_publications:
            raise SubmissionRejected("sender_not_active_editor")
        raw = _mime(s3, bucket, key, config["maxMessageBytes"])
        digest = sha256(raw).hexdigest()
        if row.get("mimeSha256") and row["mimeSha256"] != digest:
            raise SubmissionRejected("email_mime_changed")
        parsed = extract_submission(raw)
        if parsed["sender"] != sender:
            raise SubmissionRejected("mime_sender_mismatch")
        if not parsed["links"] or len(parsed["links"]) > config["maxLinks"]:
            raise SubmissionRejected("email_link_count_invalid")
        row.update(mimeSha256=digest, subject=parsed["subject"], rfcMessageId=parsed["messageId"],
                   warnings=parsed["warnings"], linkCount=len(parsed["links"]))
        store.put(monitor_id, row)
        source_url = "mailto:" + config["addresses"][0]
        provenance = {key: row[key] for key in ("sesMessageId", "sender", "recipients", "subject", "rfcMessageId",
                                               "s3Bucket", "s3Key", "mimeSha256", "accountId", "observedAt")}
        provenance.update(receiptId=receipt_key, destinationKind=config["kind"], inputTrust="untrusted-source-material")
        for link in parsed["links"]:
            # Scope + delivery + canonical URL identify the event. Existing ReferenceIntake
            # independently deduplicates the canonical source across different submissions.
            source_id = sha256(f"{message_id}\n{link['url']}".encode()).hexdigest()
            item = SourceItem(source_id, link["title"] or link["url"], link["url"], link["url"], None)
            discovery = {"pk": pk(monitor_id), "sk": f"DISC#{source_id}#000001", "monitorId": monitor_id,
                         "sourceType": "email", "sourceId": source_id, "title": item.title,
                         "canonicalUrl": item.canonical_url, "sourceItemUrl": item.source_item_url,
                         "fingerprint": item.fingerprint, "revision": 1, "observedAt": row["observedAt"],
                         "eventId": _digest([monitor_id, source_id, item.fingerprint]), "sourceUrl": source_url,
                         "runId": receipt_key, "routing": "collected", "emailProvenance": provenance,
                         "emailRoutingFingerprint": config["routingFingerprint"],
                         "emailAuthorizedPublicationIds": authorized_publications,
                         "gsi1pk": f"ROUTING#{monitor_id}#collected",
                         "gsi1sk": f"{row['observedAt']}#{source_id}#000001"}
            store.put_discovery(monitor_id, discovery)
        row.update(status="queued", errorCode=None, sectionHandoff="pending-reference-site-sweep")
        store.put(monitor_id, row)
        return {"status": "queued", "receiptId": receipt_key, "linkCount": row["linkCount"]}
    except SubmissionRejected as error:
        if row is None:
            row = {"sk": receipt_key, "sesMessageId": message_id, "ttl": int(now + RECEIPT_SECONDS)}
        row.update(status="rejected", errorCode=error.code, updatedAt=_iso(now))
        store.put(monitor_id, row)
        return {"status": "rejected", "receiptId": receipt_key, "reason": error.code}
    except Exception:
        if row is not None:
            row.update(status="failed", errorCode="intake_dependency_failed", updatedAt=_iso(now))
            store.put(monitor_id, row)
        raise
    finally:
        store.release_email_lock(monitor_id, owner)


def handler(event, context):
    """SES Lambda action entry point; IAM permits only its configured receipt rule."""
    import boto3

    records = event.get("Records") if isinstance(event, dict) else None
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise SubmissionRejected("one_ses_record_required")
    result = process_ses_record(records[0], EmailStore(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])),
                                monitor_id=os.environ["EMAIL_MONITOR_ID"], bucket=os.environ["EMAIL_RAW_BUCKET"],
                                prefix=os.environ.get("EMAIL_RAW_PREFIX", "email-submissions/"), s3=boto3.client("s3"),
                                cognito=boto3.client("cognito-idp"))
    print(json.dumps(result))  # safe status codes and hashed receipt id, never raw email/body/sender
    return result
