"""What an account spent on X in one billing cycle, counted in the one spend ledger (PPY-fa165c, slice G1).

The scope is ``x:<accountId>`` and the cycle is the owner's X billing cycle (``budget.cycle_start``), so the counter sits beside the AI spend in the shared
monitoring table under ``SPEND#<tenant>#x:<accountId>#<cycle start>`` (``spend_ledger.py``). Every charge Caducus records (``guard.SpendGuard.charged``) is added
atomically. The budget rules are in ``budget.py``; this is only the counter, in dollars as a decimal string, as it was before it moved.

Three places read or write it, each with its own role: the X queue's consumer (reads before a post, adds after it), the announcements function (the budget on the
Announcements page) and the announce agent (the runner's child, before it queues a Delivery). They share one resolver, ``ledger_from_environment``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from .. import spend_ledger

TENANT_ENVIRONMENT = "PAPYRUS_TENANT_ID"
TABLE_NAME_ENVIRONMENT = "TRIGGER_TABLE_NAME"             # the runner's own environment, and its child's
TABLE_PARAMETER_ENVIRONMENT = "PAPYRUS_MONITORING_TABLE_PARAMETER"   # the functions that read the table's name from the parameter the monitoring stack writes
MICRO = Decimal(1_000_000)


def scope_of(account_id: str) -> str:
    return f"x:{account_id}"


class SpendLedger:
    """The X spend counter over the shared table. ``table`` is the monitoring table (a boto3 Table) and ``tenant_id`` the site's tenant."""

    def __init__(self, table: Any, tenant_id: str, clock: Any = lambda: datetime.now(timezone.utc)) -> None:
        if not tenant_id:
            raise spend_ledger.SpendError("The X spend counter needs the site's tenant id: set PAPYRUS_TENANT_ID on the site's build.")
        self.table, self.tenant_id, self.clock = table, tenant_id, clock

    def spent(self, account_id: str, start: Any) -> str | None:
        held = spend_ledger.spent_in(self.table, tenant_id=self.tenant_id, scope=scope_of(account_id), start=start)
        return str(Decimal(held.microUsd) / MICRO) if held.calls else None

    def add_spend(self, account_id: str, start: Any, amount: Any, *, now: str | None = None) -> str:
        """Raise the cycle's counter by ``amount`` and return the new total."""
        moment = datetime.fromisoformat(now) if now else self.clock()
        held = spend_ledger.add_charge(self.table, tenant_id=self.tenant_id, scope=scope_of(account_id), start=start, amount=amount, moment=moment)
        return str(Decimal(held.microUsd) / MICRO)


    def reserve_search(self, account_id: str, start: Any, maximum: Decimal, cap: Decimal, moment: datetime) -> str | None:
        """Atomically count the page's worst-case charge against its separate, per-cycle read allowance.

        A reservation is intentionally not released: provider billing cannot be inferred after a failed/timed-out request.
        Returning None means no reservation was made, so the caller must not search.
        """
        charge, ceiling = spend_ledger.micro_usd(maximum), spend_ledger.micro_usd(cap)
        if charge <= 0 or charge > ceiling:
            return None
        try:
            answer = self.table.update_item(
                Key={"pk": spend_ledger.partition_key(self.tenant_id, f"{scope_of(account_id)}:opportunities", start),
                     "sk": spend_ledger.TOTAL_SORT_KEY},
                ConditionExpression="attribute_not_exists(microUsd) OR microUsd <= :remaining",
                UpdateExpression="ADD microUsd :charge, calls :one SET updatedAt = :stamp",
                ExpressionAttributeValues={":remaining": ceiling - charge, ":charge": charge, ":one": 1,
                                           ":stamp": moment.astimezone(timezone.utc).isoformat()},
                ReturnValues="ALL_NEW",
            )
        except Exception as error:
            response = getattr(error, "response", {})
            if isinstance(response, dict) and response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return None
            raise spend_ledger.SpendError("The X search budget could not be reserved.") from None
        return str(Decimal(answer["Attributes"]["microUsd"]) / MICRO)


def ledger_from_environment(environment: Mapping[str, str], *, ssm: Any = None, table: Any = None) -> SpendLedger:
    """The X spend counter for the site this process serves. The table is named by the runner's own variable, or by the parameter the monitoring stack writes."""
    tenant = (environment.get(TENANT_ENVIRONMENT) or "").strip()
    if table is None:
        import boto3

        name = (environment.get(TABLE_NAME_ENVIRONMENT) or "").strip()
        if not name:
            parameter = (environment.get(TABLE_PARAMETER_ENVIRONMENT) or "").strip()
            if not parameter:
                raise spend_ledger.SpendError(f"The spend ledger's table is not named: set {TABLE_NAME_ENVIRONMENT} or {TABLE_PARAMETER_ENVIRONMENT}.")
            name = (ssm or boto3.client("ssm")).get_parameter(Name=parameter)["Parameter"]["Value"]
        table = boto3.resource("dynamodb").Table(name)
    return SpendLedger(table, tenant)


class FunctionLedger:
    """The X spend counter as a person's own client sees it: read through the site's announcements function (``handlers.Functions.spent``), because the table belongs to the
    functions and the runner. A charge is never added from here."""

    def __init__(self, functions: Any) -> None:
        self.functions = functions

    def spent(self, account_id: str, start: Any) -> str | None:
        return self.functions.spent(account_id, start)

    def add_spend(self, account_id: str, start: Any, amount: Any, *, now: str | None = None) -> str:
        raise spend_ledger.SpendError("A charge is added by the X consumer, never from a person's client.")
