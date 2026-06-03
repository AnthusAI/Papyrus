"""Slack channel agent: enqueue console chat turns and deliver assistant replies."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

from papyrus_content.auth_commands import _is_amplify_secret_placeholder, _resolve_amplify_ssm_secret
from papyrus_newsroom.console_chat_enqueue import enqueue_console_chat_turn

_SLACK_API_BASE = "https://slack.com/api/"
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


def _resolve_secret_env(name: str, *, fallbacks: tuple[str, ...] = ()) -> str:
    candidates = (name, *fallbacks)
    for key in candidates:
        direct = str(os.environ.get(key) or "").strip()
        if direct and not _is_amplify_secret_placeholder(direct):
            return direct
    for key in candidates:
        resolved = _resolve_amplify_ssm_secret(key)
        if resolved:
            return resolved
    return ""


def slack_signing_secret() -> str:
    return _resolve_secret_env("PAPYRUS_SLACK_SIGNING_SECRET", fallbacks=("SLACK_SIGNING_SECRET",))


def slack_bot_token() -> str:
    return _resolve_secret_env("PAPYRUS_SLACK_BOT_TOKEN", fallbacks=("SLACK_BOT_TOKEN",))


def allowed_slack_user_ids() -> set[str]:
    raw = str(os.environ.get("PAPYRUS_SLACK_ALLOWED_USER_IDS") or "").strip()
    if not raw:
        return set()
    return {entry.strip() for entry in raw.split(",") if entry.strip()}


def verify_slack_request_signature(
    *,
    signing_secret: str,
    timestamp: str,
    raw_body: bytes,
    signature: str,
    max_age_seconds: int = 60 * 5,
) -> bool:
    secret = signing_secret.strip()
    if not secret or not timestamp or not signature:
        return False
    try:
        request_ts = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - request_ts) > max_age_seconds:
        return False
    base = f"v0:{timestamp}:{raw_body.decode('utf-8')}"
    digest = hmac.new(secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature.strip())


def slack_agent_instructions() -> str:
    """Channel-specific agent instructions for Slack (open-ended console chat, not email intake)."""
    return (
        "You are Papyrus, an editorial assistant for an autonomous newsroom, "
        "replying in Slack (not inbound email reference intake).\n"
        "Use execute_tactus with the papyrus.* tool surface.\n\n"
        "Be concise, accurate, and concrete. Slack has no web UI: do not use "
        "papyrus.web.navigate, papyrus.web.current_location, or assume the user "
        "can see papyrus:// pages.\n\n"
        "Raw console chat turns are working memory and are excluded from default "
        "semantic searches unless explicitly requested. When a chat produces "
        "durable insight, recommend creating an insight Message instead of making "
        "every chat turn canonical knowledge.\n\n"
        "Respond openly to questions, commands, and discussion—the same conversational "
        "stance as the web console. Do not treat every message as a citation submission. "
        "Register references or create insights only when the user shares URLs/DOIs or "
        "asks you to file, summarize, or comment on specific material.\n\n"
        "For requests like \"most recent references\" or \"tell me about recent references\", "
        "do not ask clarifying questions first: immediately call execute_tactus with a "
        "Reference.list snippet, then summarize the results.\n\n"
        "Keep Slack replies short; use bullet lists when listing references."
    )


def _slack_agent_instructions() -> str:
    return slack_agent_instructions()


def slack_thread_id(*, team_id: str, channel_id: str, thread_ts: str) -> str:
    team = str(team_id or "unknown").strip() or "unknown"
    channel = str(channel_id or "").strip()
    root = str(thread_ts or "").strip().replace(".", "-")
    return f"thread-slack-{team}-{channel}-{root}"


def chat_message_id_for_slack_event(event_id: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9]", "", str(event_id or ""))[:40] or "unknown"
    return f"message-console-slack-{token}"


def is_authorized_slack_user(user_id: str | None) -> bool:
    allowed = allowed_slack_user_ids()
    if not allowed:
        return True
    return str(user_id or "").strip() in allowed


def should_ignore_slack_event(event: dict[str, Any]) -> str | None:
    if not isinstance(event, dict):
        return "missing-event"
    if event.get("bot_id") or event.get("subtype") in {"bot_message", "message_changed", "message_deleted"}:
        return "bot-or-non-user-message"
    user = str(event.get("user") or "").strip()
    if not user:
        return "missing-user"
    if not is_authorized_slack_user(user):
        return "unauthorized-user"
    text = str(event.get("text") or "").strip()
    if not text and not event.get("files"):
        return "empty-message"
    return None


def build_slack_prompt(
    *,
    event: dict[str, Any],
    team_id: str | None,
    channel_id: str,
    thread_ts: str,
) -> str:
    user = str(event.get("user") or "slack-user").strip()
    text = str(event.get("text") or "").strip()
    urls = _URL_PATTERN.findall(text)
    lines = [
        _slack_agent_instructions(),
        "",
        f"Slack team id: {team_id or '(unknown)'}",
        f"Slack channel id: {channel_id}",
        f"Slack thread ts: {thread_ts}",
        f"Slack user id: {user}",
        "",
        "User message:",
        text or "(no text; see files metadata if present)",
    ]
    files = event.get("files")
    if isinstance(files, list) and files:
        lines.extend(["", "Slack files JSON:", json.dumps(files, indent=2, sort_keys=True)])
    if urls:
        lines.extend(["", f"Detected URL count: {len(urls)}", "URLs:", *[f"- {url}" for url in urls]])
    return "\n".join(lines).strip()


def enqueue_console_chat_for_slack_message(
    client: Any,
    *,
    event: dict[str, Any],
    team_id: str | None,
    event_id: str,
) -> dict[str, Any]:
    channel_id = str(event.get("channel") or "").strip()
    thread_ts = str(event.get("thread_ts") or event.get("ts") or "").strip()
    if not channel_id or not thread_ts:
        raise ValueError("Slack message event requires channel and ts.")
    user = str(event.get("user") or "slack-user").strip()
    thread_id = slack_thread_id(team_id=team_id or "", channel_id=channel_id, thread_ts=thread_ts)
    prompt = build_slack_prompt(
        event=event,
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )
    return enqueue_console_chat_turn(
        client,
        thread_id=thread_id,
        thread_title=f"Slack {channel_id}",
        thread_summary="Slack agent conversation",
        primary_anchor_kind="slack_thread",
        primary_anchor_id=thread_id,
        created_by_label=f"slack:{user}",
        prompt=prompt,
        message_summary=(str(event.get("text") or "Slack message"))[:180],
        source="slack",
        channel="slack",
        channel_metadata={
            "slackTeamId": team_id,
            "slackChannelId": channel_id,
            "slackThreadTs": thread_ts,
            "slackUserId": user,
            "slackEventId": event_id,
        },
        thread_metadata={
            "slackTeamId": team_id,
            "slackChannelId": channel_id,
            "slackThreadTs": thread_ts,
        },
        capture_model_context=True,
        chat_message_id=chat_message_id_for_slack_event(event_id),
    )


def slack_api_request(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = slack_bot_token()
    if not token:
        raise RuntimeError("PAPYRUS_SLACK_BOT_TOKEN is not configured.")
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{_SLACK_API_BASE}{method}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Slack API HTTP {error.code}: {raw}") from error
    parsed = json.loads(raw) if raw else {}
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Slack API returned non-object payload for {method}.")
    if not parsed.get("ok"):
        raise RuntimeError(str(parsed.get("error") or f"Slack API {method} failed."))
    return parsed


def post_slack_thread_reply(*, channel_id: str, thread_ts: str, text: str) -> dict[str, Any]:
    trimmed = text.strip()
    if not trimmed:
        trimmed = "(Papyrus had no text response.)"
    # Slack chat.postMessage limit is large; keep a safety cap for Lambda payloads.
    if len(trimmed) > 12000:
        trimmed = trimmed[:11900] + "\n…(truncated)"
    return slack_api_request(
        "chat.postMessage",
        {
            "channel": channel_id,
            "thread_ts": thread_ts,
            "text": trimmed,
            "unfurl_links": False,
            "unfurl_media": False,
        },
    )


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def should_process_slack_delivery_stream_record(
    *,
    event_name: str,
    assistant_message: dict[str, Any],
    previous_message: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Return whether a DynamoDB stream record should trigger Slack delivery.

    Delivery marks the assistant Message with slackDeliveredAt, which emits a MODIFY.
    Ignore metadata-only MODIFY events on already-completed turns to avoid loops.
    """
    assistant_meta = _parse_metadata(assistant_message.get("metadata"))
    if assistant_meta.get("slackDeliveredAt"):
        return False, "already-delivered"

    event = str(event_name or "").strip().upper()
    if event == "INSERT":
        return True, None

    if event != "MODIFY":
        return False, f"unsupported-event:{event_name or 'missing'}"

    if not previous_message:
        return True, None

    previous_meta = _parse_metadata(previous_message.get("metadata"))
    if previous_meta.get("slackDeliveredAt"):
        return False, "already-delivered-previous-image"

    previous_status = str(previous_message.get("responseStatus") or "").strip().upper()
    current_status = str(assistant_message.get("responseStatus") or "").strip().upper()
    if previous_status == "COMPLETED" and current_status == "COMPLETED":
        return False, "completed-metadata-touch"

    return True, None


def deliver_slack_reply_for_assistant_message(
    client: Any,
    *,
    assistant_message: dict[str, Any],
) -> dict[str, Any]:
    if str(assistant_message.get("role") or "").upper() != "ASSISTANT":
        return {"ok": False, "skipped": True, "reason": "not-assistant"}
    if str(assistant_message.get("responseStatus") or "").upper() != "COMPLETED":
        return {"ok": False, "skipped": True, "reason": "not-completed"}
    assistant_meta = _parse_metadata(assistant_message.get("metadata"))
    if assistant_meta.get("slackDeliveredAt"):
        return {"ok": True, "skipped": True, "reason": "already-delivered"}

    thread_id = str(assistant_message.get("threadId") or "").strip()
    if not thread_id:
        return {"ok": False, "skipped": True, "reason": "missing-thread-id"}

    thread = client.get_record("MessageThread", thread_id) or {}
    thread_meta = _parse_metadata(thread.get("metadata"))
    if str(thread_meta.get("channel") or "") != "slack":
        return {"ok": False, "skipped": True, "reason": "not-slack-thread"}

    channel_id = str(thread_meta.get("slackChannelId") or "").strip()
    thread_ts = str(thread_meta.get("slackThreadTs") or "").strip()
    if not channel_id or not thread_ts:
        return {"ok": False, "skipped": True, "reason": "missing-slack-routing"}

    content = str(assistant_message.get("content") or "").strip()
    if not content:
        content = str(assistant_message.get("summary") or "").strip()
    post_result = post_slack_thread_reply(channel_id=channel_id, thread_ts=thread_ts, text=content)

    from datetime import datetime, timezone

    delivered_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    assistant_meta["slackDeliveredAt"] = delivered_at
    assistant_meta["slackDeliveryTs"] = post_result.get("ts")
    client.graphql(
        """
        mutation MarkSlackAssistantDelivered($input: UpdateMessageInput!) {
          updateMessage(input: $input) { id }
        }
        """,
        {
            "input": {
                "id": str(assistant_message.get("id") or "").strip(),
                "metadata": json.dumps(assistant_meta, sort_keys=True),
                "updatedAt": delivered_at,
            }
        },
    )
    return {
        "ok": True,
        "posted": True,
        "channelId": channel_id,
        "threadTs": thread_ts,
        "slackTs": post_result.get("ts"),
    }


def process_slack_events_payload(
    client: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    payload_type = str(payload.get("type") or "").strip()
    if payload_type == "url_verification":
        return {"ok": True, "challenge": payload.get("challenge")}

    if payload_type != "event_callback":
        return {"ok": True, "ignored": True, "reason": f"unsupported-type:{payload_type or 'missing'}"}

    event_id = str(payload.get("event_id") or "").strip()
    team_id = str(payload.get("team_id") or "").strip() or None
    event = payload.get("event")
    if not isinstance(event, dict):
        return {"ok": False, "error": "missing-event"}

    event_type = str(event.get("type") or "").strip()
    if event_type not in {"message", "app_mention"}:
        return {"ok": True, "ignored": True, "reason": f"unsupported-event:{event_type}"}

    ignore_reason = should_ignore_slack_event(event)
    if ignore_reason:
        return {"ok": True, "ignored": True, "reason": ignore_reason}

    if not event_id:
        event_id = f"{event_type}-{event.get('ts') or 'unknown'}"

    existing_id = chat_message_id_for_slack_event(event_id)
    existing = client.get_record("Message", existing_id)
    if existing:
        return {"ok": True, "idempotent": True, "chatMessageId": existing_id}

    chat = enqueue_console_chat_for_slack_message(
        client,
        event=event,
        team_id=team_id,
        event_id=event_id,
    )
    return {"ok": True, "chat": chat, "eventId": event_id}
