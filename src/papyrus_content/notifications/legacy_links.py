"""Old newsletter manage and unsubscribe links, honoured for a dated period after a site moves to notifications (PPY-6b2d35).

THIS MODULE IS DELETED, NOT KEPT. Mail already sent carries manage and unsubscribe tokens in the newsletter's format. For the
period the owner sets (the ``--old-links-until`` date given to the migration, which is also the expiry of every alias row), the
router accepts such a token on exactly the four manage-token actions and swaps it for the subscriber's new manage token, found
through the alias row the migration wrote (``ALIAS#newsletter#<old subscriber id>``). A confirm token is never accepted: a
confirmation in the old format can no longer be used, because nothing pending is migrated.

Retirement is one change, made once the alias date has passed (DynamoDB deletes the alias rows by TTL) and the migration is
verified on every site: delete this file, its use in ``handler.route``, the ``legacy`` field in ``runtime.py``,
``Settings.legacy_newsletter_key_parameter``, the ``LEGACY_NEWSLETTER_KEY_PARAMETER`` environment variable and its IAM grant in
``amplify/plugins/notifications/papyrus.plugin.ts``, and the ``legacyNewsletterLinks`` plugin setting. Nothing else knows the
newsletter's token format.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from papyrus_content.newsletter import tokens as newsletter_tokens

#: The alias source name: the migration writes ``ALIAS#newsletter#<hid>`` rows (``migration.SOURCE``).
SOURCE = "newsletter"
#: The two routes of the old pages that carried a manage token: manage (preferences, delete) and unsubscribe.
ACTIONS = frozenset(["preferences_state", "update_preferences", "unsubscribe", "delete_subscriber"])


class LegacyLinks:
    def __init__(self, token_key: bytes, audience: Any, now: Callable[[], float]) -> None:
        self._key = token_key
        self._audience = audience
        self._now = now

    def translate(self, event: Mapping[str, Any]) -> Mapping[str, Any]:
        """The event with an old-format manage token replaced by the new one. A token that is not old-format passes through
        untouched; an old-format token with no alias (never migrated, or past its date) becomes an empty token, which Caducus
        answers as invalid."""
        if event.get("action") not in ACTIONS:
            return event
        try:
            claims = newsletter_tokens.verify(self._key, event.get("token"), "manage", self._now())
        except newsletter_tokens.InvalidToken:
            return event
        return {**event, "token": self._audience.manage_token_for_alias(SOURCE, claims.hid) or ""}
