"""Python twin of the Prospectus usage sender (`@anthus/cost-accounting/usage`, Prospectus docs/COST_ACCOUNTING.md).

Papyrus's model calls run in Python Lambdas, and the Prospectus package ships only a TypeScript sender. This module
sends the same message (version 1) to the same per-product queue with the same rules:

- `record` is synchronous and never touches the network; invalid input raises at once.
- `flush` sends one message per Account, deployment and UTC day, and never raises. A message that fails to send is
  kept and retried with the same operation ID, so Prospectus counts it once.
- A Papyrus site sends as product `papyrus-<site>` with its site ID as the deployment, only to its own queue,
  `prospectus-usage-papyrus-<site>`. Quantities only, never dollars.

In a Lambda, call `flush()` before the invocation returns: a frozen process loses what is only in memory.

The site's infrastructure sets the environment (amplify/cost-attribution.ts): `PROSPECTUS_USAGE_QUEUE_URL` and
`PAPYRUS_SITE_ID`. No Account ID is configured: a runtime that has no verified customer Account (the AppSync Lambda
resolvers, which the browser calls directly) records as `"owner"`, and Prospectus charges the one Account holding the
active papyrus-<site> entitlement (with none or several, the message is refused into the dead-letter queue, with an
alarm). A runtime that has a verified Account (such as the Next.js server after Prospectus authorize) passes its UUID.
Never pass an Account ID the browser supplied.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

COST_APPS = ("papyrus", "cyclotron", "babulus", "chatticus", "prospectus")
PROSPECTUS_REGION = "us-east-1"
DEPLOYMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
ITEM_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9_:-]*)+$")
QUEUE_URL_PATTERN = re.compile(r"^https://sqs\.[a-z0-9-]+\.amazonaws\.com/\d{12}/prospectus-usage-([a-z0-9-]+)$")
MAX_SAFE_INTEGER = 2**53 - 1
# The deployment's owning Account, which Prospectus looks up from the entitlement (needs a deployment).
OWNER = "owner"

# Item kinds Papyrus reports. Each must exist in the Prospectus price list; an unknown kind is refused there, never free.
OPENAI_INPUT_TOKENS = "openai.tokens.input"
OPENAI_OUTPUT_TOKENS = "openai.tokens.output"
JEV_TOKENS = "jev.tokens"


class UsageError(ValueError):
    """Invalid sender configuration or usage record."""


def usage_queue_url(product: str, prospectus_account: str, region: str = PROSPECTUS_REGION) -> str:
    """A product's own queue in the Prospectus account (the same URL as the package's `usageQueueUrl`)."""
    if not re.fullmatch(r"\d{12}", prospectus_account or ""):
        raise UsageError("Usage sender: the Prospectus AWS account is 12 digits.")
    return f"https://sqs.{region}.amazonaws.com/{prospectus_account}/prospectus-usage-{product}"


def site_usage_product(site_id: str) -> str:
    """The Prospectus product a dedicated Papyrus site sends as.

    Seam for the shared multi-tenant tier (Prospectus kanbus-f45f7f): that tier will send to one `papyrus` queue with
    each tenant's site ID as the deployment. It is not built; a dedicated site always sends as `papyrus-<site>`.
    """
    if not DEPLOYMENT_PATTERN.match(site_id or ""):
        raise UsageError("Usage sender: the site ID must be lower-case letters, digits and hyphens.")
    return f"papyrus-{site_id}"


def _today(now_ms: float) -> int:
    return int(datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y%m%d"))


def _sqs_send(queue_url: str, body: str) -> None:
    import boto3  # deferred: only a deployed sender needs it

    global _SQS_CLIENT
    with _SQS_LOCK:
        if _SQS_CLIENT is None:
            _SQS_CLIENT = boto3.client("sqs", region_name=PROSPECTUS_REGION)
    _SQS_CLIENT.send_message(QueueUrl=queue_url, MessageBody=body)


_SQS_CLIENT: Any = None
_SQS_LOCK = threading.Lock()


class UsageSender:
    """Tallies usage in memory and sends it to the product's Prospectus usage queue."""

    def __init__(
        self,
        *,
        product: str,
        app: str,
        deployment: str | None = None,
        queue_url: str | None = None,
        send: Callable[[str, str], None] | None = None,
        now: Callable[[], float] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        if app not in COST_APPS:
            raise UsageError("Usage sender: unknown app.")
        if deployment is not None and not DEPLOYMENT_PATTERN.match(deployment):
            raise UsageError("Usage sender: deployment must be lower-case letters, digits and hyphens.")
        if app == "papyrus" and product != f"papyrus-{deployment}":
            raise UsageError("Usage sender: a Papyrus site sends as papyrus-<site> with its site ID as the deployment.")
        queue_url = queue_url if queue_url is not None else os.environ.get("PROSPECTUS_USAGE_QUEUE_URL")
        match = QUEUE_URL_PATTERN.match(queue_url or "")
        if not match or match.group(1) != product:
            raise UsageError("Usage sender: PROSPECTUS_USAGE_QUEUE_URL must be this product's Prospectus usage queue.")
        self.product = product
        self.app = app
        self.deployment = deployment
        self.queue_url = queue_url
        self._send = send or _sqs_send
        self._now = now or (lambda: time.time() * 1000)
        self._on_error = on_error
        self._tally: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._pending: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, account_id: str, items: Iterable[Mapping[str, Any]], deployment: str | None = None) -> None:
        """Adds usage to the in-memory tally. Synchronous and network-free; invalid input raises at once."""
        deployment = self.deployment if deployment is None else deployment
        if account_id == OWNER and deployment is None:
            raise UsageError('Usage sender: accountId "owner" needs a deployment.')
        if account_id != OWNER and (not isinstance(account_id, str) or not UUID_PATTERN.match(account_id)):
            raise UsageError('Usage sender: accountId must be a lower-case Account UUID or "owner".')
        if deployment is not None and not DEPLOYMENT_PATTERN.match(deployment):
            raise UsageError("Usage sender: deployment must be lower-case letters, digits and hyphens.")
        items = list(items)
        for item in items:
            kind, quantity = item.get("itemKind"), item.get("quantity")
            if not isinstance(kind, str) or len(kind) > 96 or not ITEM_KIND_PATTERN.match(kind):
                raise UsageError("Usage sender: itemKind must be a namespaced kind such as openai.tokens.input.")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0 or quantity > MAX_SAFE_INTEGER:
                raise UsageError("Usage sender: quantity must be a whole, non-negative number.")
        day = _today(self._now())
        key = (account_id, deployment or "", day)
        with self._lock:
            group = self._tally.setdefault(key, {"accountId": account_id, "deployment": deployment, "day": day, "items": {}})
            for item in items:
                total = group["items"].get(item["itemKind"], 0) + item["quantity"]
                if total > MAX_SAFE_INTEGER:
                    raise UsageError("Usage sender: quantity overflow.")
                group["items"][item["itemKind"]] = total

    def flush(self) -> None:
        """Sends everything tallied so far, plus anything a previous flush could not send. Never raises."""
        with self._lock:
            for group in self._tally.values():
                items = [{"itemKind": kind, "quantity": quantity} for kind, quantity in group["items"].items() if quantity > 0]
                if not items:
                    continue
                message: dict[str, Any] = {"version": 1, "operationId": str(uuid.uuid4()), "accountId": group["accountId"], "app": self.app}
                if group["deployment"] is not None:
                    message["deployment"] = group["deployment"]
                message["day"] = group["day"]
                message["items"] = items
                self._pending.append(message)
            self._tally.clear()
            pending, self._pending = self._pending, []
        unsent = []
        for message in pending:
            try:
                self._send(self.queue_url, json.dumps(message, separators=(",", ":")))
            except Exception:  # noqa: BLE001 - a failed send is kept and retried; never fails the caller
                unsent.append(message)
                if self._on_error:
                    self._on_error("send_failed")
        with self._lock:
            self._pending = unsent + self._pending

    @property
    def backlog(self) -> int:
        """Messages waiting to be sent, for health checks and tests."""
        return len(self._pending) + len(self._tally)


class SiteUsage:
    """A dedicated site's sender. Records nothing when not configured.

    Usage is charged to `"owner"` (the site's owning Account, from the papyrus-<site> entitlement) unless the caller
    passes `account_id`: the seam for a runtime that holds a verified Account UUID.
    """

    def __init__(self, sender: UsageSender | None) -> None:
        self.sender = sender

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None, **sender_options: Any) -> "SiteUsage":
        """The sender the site's infrastructure configured, or an inactive one outside a deployed site.

        Inactive means `PROSPECTUS_USAGE_QUEUE_URL` is unset (a local run or a test). A queue URL without a valid
        `PAPYRUS_SITE_ID`, or for another product's queue, raises instead of silently dropping usage.
        """
        environ = os.environ if environ is None else environ
        queue_url = (environ.get("PROSPECTUS_USAGE_QUEUE_URL") or "").strip()
        if not queue_url:
            return cls(None)
        site_id = (environ.get("PAPYRUS_SITE_ID") or "").strip()
        sender = UsageSender(product=site_usage_product(site_id), app="papyrus", deployment=site_id, queue_url=queue_url, **sender_options)
        return cls(sender)

    @property
    def active(self) -> bool:
        return self.sender is not None

    def record(self, items: Iterable[Mapping[str, Any]], account_id: str = OWNER) -> None:
        """Records non-zero items for `account_id`: a verified Account UUID, or `"owner"` (the default)."""
        if self.sender is None:
            return
        items = [item for item in items if item.get("quantity")]
        if items:
            self.sender.record(account_id, items)

    def record_openai(self, usage: Mapping[str, Any] | None, account_id: str = OWNER) -> None:
        """Records an OpenAI response's `usage` block (chat, responses or embeddings)."""
        if not usage:
            return
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens")) or 0
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens")) or 0
        self.record([
            {"itemKind": OPENAI_INPUT_TOKENS, "quantity": int(input_tokens)},
            {"itemKind": OPENAI_OUTPUT_TOKENS, "quantity": int(output_tokens)},
        ], account_id)

    def record_humanus_check(self, result: Mapping[str, Any] | None, account_id: str = OWNER) -> None:
        """Records the Jev classifier tokens a Humanus check reports in `usage.classifierInputTokens`."""
        usage = (result or {}).get("usage") or {}
        tokens = usage.get("classifierInputTokens") or 0
        self.record([{"itemKind": JEV_TOKENS, "quantity": int(tokens)}], account_id)

    def flush(self) -> None:
        if self.sender is not None:
            self.sender.flush()


_SITE_USAGE: SiteUsage | None = None
_SITE_USAGE_LOCK = threading.Lock()


def site_usage() -> SiteUsage:
    """The process's site sender, built once from the environment; inactive outside a deployed site.

    Library code that makes a model call records into it; the Lambda handler that owns the invocation flushes it.
    """
    global _SITE_USAGE
    with _SITE_USAGE_LOCK:
        if _SITE_USAGE is None:
            _SITE_USAGE = SiteUsage.from_environment()
        return _SITE_USAGE
