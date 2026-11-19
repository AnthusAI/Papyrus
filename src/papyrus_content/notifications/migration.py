"""Moving a site's newsletter subscribers, consent and suppression into notifications (PPY-6b2d35).

Reads the newsletter table (``newsletter.store``: ``SUB#<hid>/PROFILE``, ``SUB#<hid>/LIST#<list>``, ``SUPP#<hid>/SUPP``) and writes
the site's notifications table through Caducus's public audience (``import_subscriber`` and ``add_alias``, Caducus 0.4.0). Four steps,
each safe to repeat:

* ``plan``    reads only. Per list: confirmed, pending and unsubscribed memberships; consent coverage; suppressed addresses (masked);
              what will be carried and what will not, and ``problems`` that stop a real run (a list the notifications settings do
              not declare, a confirmed subscriber with no consent evidence).
* ``apply``   imports every confirmed subscriber and every suppressed one, with the original consent evidence copied and marked
              ``migrated`` (no confirmation is ever mailed), writes the alias row of the old subscriber id (the old links keep
              working until the date given), then settles anyone who left the newsletter since an earlier run (unsubscribed or
              suppressed there), so a re-run never leaves a reader subscribed who asked to stop.
* ``verify``  compares source and target subscriber by subscriber and prints counts per list, suppressed and consent records.
* Nothing is carried for a pending signup (never consented) or an address that unsubscribed (there is nothing to protect: the
  newsletter keeps no further use for it and a new signup is a fresh consent). A suppression row whose profile is gone cannot be
  carried (it holds no address; SES's account suppression list, shared by both systems, still blocks the address).

Nothing here touches AWS by itself: ``Source`` reads through whatever DynamoDB client it is given and ``Target`` wraps the audience
the caller built. ``migration_cli.py`` builds the real ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from papyrus_content.newsletter.store import Store, _de, _ser

from .legacy_links import SOURCE

SUPPRESSION_REASONS = ("bounce", "complaint", "manual")
PROFILE_STATUSES = ("pending", "confirmed", "unsubscribed")


def mask(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


# -- the source ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Subscriber:
    hid: str
    address: str
    status: str                      # the profile's: pending, confirmed or unsubscribed
    lists: tuple[str, ...]           # lists subscribed
    pending_lists: tuple[str, ...]
    unsubscribed_lists: tuple[str, ...]
    consent: Mapping[str, Any] | None
    suppression: str | None          # bounce, complaint or manual

    @property
    def carried(self) -> bool:
        """A confirmed subscriber with a list, or anyone suppressed (whose suppression must stay)."""
        return (self.status == "confirmed" and bool(self.lists)) or self.suppression in SUPPRESSION_REASONS


@dataclass(frozen=True)
class Snapshot:
    subscribers: tuple[Subscriber, ...]
    orphan_suppressions: int         # suppression rows with no profile: the address is unknown


def read_source(store: Store, now: float) -> Snapshot:
    """Scan the newsletter table once. A pending row past its TTL is skipped, as DynamoDB will delete it."""
    profiles: dict[str, dict[str, Any]] = {}
    memberships: dict[str, dict[str, str]] = {}
    suppressions: dict[str, str] = {}
    start: dict[str, Any] | None = None
    while True:
        page = store.client.scan(
            TableName=store.table_name,
            FilterExpression="begins_with(pk, :sub) OR begins_with(pk, :supp)",
            ExpressionAttributeValues=_ser({":sub": "SUB#", ":supp": "SUPP#"}),
            **({"ExclusiveStartKey": start} if start else {}),
        )
        for raw in page.get("Items", []):
            row = _de(raw)
            if "expiresAt" in row and row["expiresAt"] < now:
                continue
            if row["pk"].startswith("SUPP#"):
                suppressions[row["pk"].removeprefix("SUPP#")] = str(row.get("reason"))
            elif row["sk"] == "PROFILE":
                profiles[row["pk"].removeprefix("SUB#")] = row
            elif row["sk"].startswith("LIST#"):
                memberships.setdefault(row["pk"].removeprefix("SUB#"), {})[row["sk"].removeprefix("LIST#")] = str(row.get("status"))
        start = page.get("LastEvaluatedKey")
        if not start:
            break

    def listed(hid: str, status: str) -> tuple[str, ...]:
        return tuple(sorted(list_id for list_id, value in memberships.get(hid, {}).items() if value == status))

    subscribers = tuple(
        Subscriber(
            hid=hid,
            address=str(row.get("email", "")),
            status=str(row.get("status")),
            lists=listed(hid, "subscribed"),
            pending_lists=listed(hid, "pending"),
            unsubscribed_lists=listed(hid, "unsubscribed"),
            consent=row.get("consent") if isinstance(row.get("consent"), dict) else None,
            suppression=suppressions.get(hid),
        )
        for hid, row in sorted(profiles.items())
        if row.get("status") in PROFILE_STATUSES
    )
    return Snapshot(subscribers, sum(1 for hid in suppressions if hid not in profiles))


# -- the plan ------------------------------------------------------------------------------------------------------------


@dataclass
class Plan:
    carried: list[Subscriber] = field(default_factory=list)
    per_list: dict[str, dict[str, int]] = field(default_factory=dict)   # list -> confirmed / pending / unsubscribed memberships
    consent: dict[str, int] = field(default_factory=lambda: {"with_evidence": 0, "without_evidence": 0})
    suppressed: dict[str, int] = field(default_factory=dict)            # reason -> count
    suppressed_addresses: list[str] = field(default_factory=list)       # masked
    orphan_suppressions: int = 0
    not_carried: dict[str, int] = field(default_factory=lambda: {"pending": 0, "unsubscribed": 0})
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "carried": len(self.carried),
            "perList": self.per_list,
            "consent": self.consent,
            "suppressed": self.suppressed,
            "suppressedAddresses": self.suppressed_addresses,
            "suppressionsWithoutProfile": self.orphan_suppressions,
            "notCarried": self.not_carried,
            "problems": self.problems,
        }


def build_plan(snapshot: Snapshot, declared_lists: Sequence[str]) -> Plan:
    """What a run would do. ``declared_lists`` are the list ids the site's notifications settings declare."""
    plan = Plan(orphan_suppressions=snapshot.orphan_suppressions)
    unknown: set[str] = set()
    for sub in snapshot.subscribers:
        for status, ids in (("confirmed", sub.lists), ("pending", sub.pending_lists), ("unsubscribed", sub.unsubscribed_lists)):
            for list_id in ids:
                counts = plan.per_list.setdefault(list_id, {"confirmed": 0, "pending": 0, "unsubscribed": 0})
                counts[status] += 1
        if not sub.carried:
            if sub.status in plan.not_carried:
                plan.not_carried[sub.status] += 1
            continue
        plan.carried.append(sub)
        plan.consent["with_evidence" if sub.consent else "without_evidence"] += 1
        if sub.suppression:
            plan.suppressed[sub.suppression] = plan.suppressed.get(sub.suppression, 0) + 1
            plan.suppressed_addresses.append(mask(sub.address))
        unknown.update(list_id for list_id in sub.lists if list_id not in declared_lists)
    for list_id in sorted(unknown):
        plan.problems.append(f"list_not_declared:{list_id}")
    if plan.consent["without_evidence"]:
        plan.problems.append(f"no_consent_evidence:{plan.consent['without_evidence']}")
    return plan


# -- the target ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """The site's public audience, and how it turns an address into the recipient key (``Runtime.recipient_key``)."""

    audience: Any
    recipient_key: Callable[[str], str]


@dataclass
class Result:
    imported: int = 0
    unchanged: int = 0
    refused: list[str] = field(default_factory=list)     # masked addresses Caducus refused (erased there, or two lists of one family)
    settled: int = 0                                      # list memberships ended because the reader left the newsletter since
    aliases: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"imported": self.imported, "unchanged": self.unchanged, "refused": self.refused, "settled": self.settled, "aliases": self.aliases}


class Refused(Exception):
    """A real run was asked for while the plan still has problems."""


def _target_state(target: Target, address: str) -> tuple[dict[str, str], str | None, list[Mapping[str, Any]]] | None:
    """(lists the reader holds by id, suppression reason, migrated consent records), or None when the target holds nobody."""
    answer = target.audience.export(address)
    body = answer["body"]
    if body.get("status") != "ready":
        return None
    migrated = [record for record in body["consent"] if record.get("source") == "migrated" and record.get("from") == SOURCE]
    return body["lists"], body.get("suppression"), migrated


def apply(plan: Plan, snapshot: Snapshot, target: Target, *, old_links_until: int, declared_lists: Sequence[str]) -> Result:
    """Import, alias and settle. Idempotent: a second run reports every subscriber ``unchanged`` and settles nothing."""
    if plan.problems:
        raise Refused(", ".join(plan.problems))
    result = Result()
    for sub in plan.carried:
        outcome = target.audience.import_subscriber(
            sub.address, list(sub.lists), dict(sub.consent or {}), SOURCE, suppressed=sub.suppression
        )
        if outcome == "refused":
            result.refused.append(mask(sub.address))
            continue
        result.imported += outcome == "imported"
        result.unchanged += outcome == "unchanged"
        target.audience.add_alias(SOURCE, sub.hid, sub.address, old_links_until)
        result.aliases += 1
    for sub in snapshot.subscribers:
        state = _target_state(target, sub.address) if sub.address else None
        if state is None or not state[2]:
            continue   # nobody there, or someone who joined in the new system on their own: not ours to touch
        held = {list_id for list_id, status in state[0].items() if status == "subscribed" and list_id in declared_lists}
        leaving = sorted(held - set(sub.lists if sub.status == "confirmed" else ()))
        if not leaving:
            continue
        token = target.audience.manage_token(target.recipient_key(sub.address))
        if sub.status != "confirmed" or not sub.lists:
            target.audience.unsubscribe(token)
        else:
            for list_id in leaving:
                target.audience.unsubscribe(token, list_id)
        result.settled += len(leaving)
    return result


# -- verification --------------------------------------------------------------------------------------------------------


@dataclass
class Verification:
    per_list: dict[str, dict[str, int]] = field(default_factory=dict)   # list -> {"source": n, "target": n}
    suppressed: dict[str, int] = field(default_factory=lambda: {"source": 0, "target": 0})
    consent: dict[str, int] = field(default_factory=lambda: {"source": 0, "target": 0})
    aliases: dict[str, int] = field(default_factory=lambda: {"source": 0, "target": 0})
    mismatches: list[str] = field(default_factory=list)                  # hids (no address) with what differs

    @property
    def ok(self) -> bool:
        return not self.mismatches and all(c["source"] == c["target"] for c in self.per_list.values()) and all(
            row["source"] == row["target"] for row in (self.suppressed, self.consent, self.aliases)
        )

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "perList": self.per_list, "suppressed": self.suppressed, "consent": self.consent, "aliases": self.aliases, "mismatches": self.mismatches}


def verify(plan: Plan, target: Target, *, declared_lists: Sequence[str]) -> Verification:
    """Subscriber by subscriber: the lists held, the suppression, a migrated consent record and the alias must match the source."""
    report = Verification()
    for sub in plan.carried:
        report.consent["source"] += 1
        report.aliases["source"] += 1
        if sub.suppression:
            report.suppressed["source"] += 1
        for list_id in sub.lists:
            report.per_list.setdefault(list_id, {"source": 0, "target": 0})["source"] += 1
        state = _target_state(target, sub.address)
        if state is None:
            report.mismatches.append(f"{sub.hid}:missing")
            continue
        held = {list_id for list_id, status in state[0].items() if status == "subscribed" and list_id in declared_lists}
        for list_id in held & set(sub.lists):
            report.per_list[list_id]["target"] += 1
        if held != set(sub.lists):
            report.mismatches.append(f"{sub.hid}:lists")
        if state[2]:
            report.consent["target"] += 1
        if sub.suppression:
            report.suppressed["target"] += state[1] == sub.suppression
        if target.audience.resolve_alias(SOURCE, sub.hid) == target.recipient_key(sub.address):
            report.aliases["target"] += 1
    return report


# -- the printed report --------------------------------------------------------------------------------------------------


def render_plan(plan: Plan) -> str:
    lines = [f"Carried to notifications: {len(plan.carried)} subscribers"]
    for list_id, counts in sorted(plan.per_list.items()):
        lines.append(f"  list {list_id}: {counts['confirmed']} confirmed, {counts['pending']} pending, {counts['unsubscribed']} unsubscribed")
    lines.append(f"Consent evidence: {plan.consent['with_evidence']} with, {plan.consent['without_evidence']} without")
    lines.append("Suppressed: " + (", ".join(f"{reason} {count}" for reason, count in sorted(plan.suppressed.items())) or "none"))
    lines += [f"  {address}" for address in plan.suppressed_addresses]
    lines.append(f"Suppression rows with no profile (no address to carry; SES's shared list still blocks them): {plan.orphan_suppressions}")
    lines.append(f"Not carried: {plan.not_carried['pending']} pending (never consented), {plan.not_carried['unsubscribed']} unsubscribed")
    lines += [f"PROBLEM {problem}" for problem in plan.problems]
    return "\n".join(lines)


def render_verification(report: Verification) -> str:
    lines = ["Verification: " + ("every count matches" if report.ok else "DOES NOT MATCH")]
    for list_id, counts in sorted(report.per_list.items()):
        lines.append(f"  list {list_id}: source {counts['source']}, target {counts['target']}")
    for name, row in (("suppressed", report.suppressed), ("consent records", report.consent), ("old-link aliases", report.aliases)):
        lines.append(f"  {name}: source {row['source']}, target {row['target']}")
    lines += [f"MISMATCH {entry}" for entry in report.mismatches]
    return "\n".join(lines)
