"""The one spend ledger: a counter for each scope and budget cycle (PPY-fa165c, slice G1).

A scope is what is being counted (``ai`` for a site's whole model spend, ``ai:<responsibility>`` for one agent) and a cycle is the budget period of the site's
agent policy (``day``, ``week`` or ``month``) that contains the moment. The ledger holds numbers only, in integer millionths of a dollar so that adding is exact.

It lives in the shared monitoring table, because the procedure runner is one stack for every site and a site's own tables cannot be named in its role. A
row's partition key starts with ``SPEND#<tenant>#``, which is the one key prefix the runner's role may write besides its trigger rows::

    pk = SPEND#<tenant>#<scope>#<cycle start>   sk = TOTAL        microUsd, calls, unpricedCalls, updatedAt
    pk = SPEND#<tenant>#<scope>#<cycle start>   sk = RUN#<run id> a marker: this run was counted here (ttl: it only has to outlive a redelivery)
    pk = SPEND#<tenant>#ai:<responsibility>#history   sk = RUNS   runs, sumLogMicroUsd, sumSquaredLogMicroUsd (the agent's cost history, below)

A run is counted once. The markers and the totals of every scope the run belongs to are written in one transaction, and a marker that already exists cancels the
whole transaction, so a wake that is delivered twice adds its cost once. A model call with no price is counted in ``unpricedCalls`` and never as free: the total
of a cycle that has any is ``partial`` and says how many calls it does not include.

An agent's **cost history** (PPY-eef85d, slice G3) is three running sums over the natural logarithm of each fully priced run's cost in millionths of a dollar:
how many runs, the sum of the logarithms and the sum of their squares. They are added in the same transaction as the run's markers, so a redelivered wake adds
to the history once, and they are all ``unusual_cost.py`` needs to judge the next run against every earlier one without reading any run record.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping

PERIODS = ("day", "week", "month")
KEY_PREFIX = "SPEND#"
TOTAL_SORT_KEY = "TOTAL"
MARKER_SORT_PREFIX = "RUN#"
MARKER_LIFETIME = timedelta(days=30)   # longer than the queue keeps a message, so no redelivery meets a missing marker
MICRO = Decimal(1_000_000)
HISTORY_CYCLE = "history"
HISTORY_SORT_KEY = "RUNS"
LOGARITHM_PLACES = Decimal("0.000000001")   # a logarithm is stored to nine places, so the running sums add exactly in DynamoDB's decimal numbers


class SpendError(Exception):
    """The ledger could not be written."""


def cycle_start(period: str, moment: datetime) -> date:
    """The first day of the budget cycle that contains ``moment`` (UTC): the day itself, the Monday of its week, or the first of its month."""
    if period not in PERIODS:
        raise ValueError(f"A budget period is one of {', '.join(PERIODS)}, not {period!r}.")
    day = moment.astimezone(timezone.utc).date()
    if period == "day":
        return day
    if period == "week":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def next_cycle_start(period: str, moment: datetime) -> date:
    """The first day of the budget cycle after the one that contains ``moment``: when the waiting paid work of a site at its budget runs (PPY-9376f8)."""
    start = cycle_start(period, moment)
    if period == "day":
        return start + timedelta(days=1)
    if period == "week":
        return start + timedelta(days=7)
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def scopes_of(responsibility: str | None) -> list[str]:
    """The scopes a run's spend is added to: the site's, and the agent's when an agent made the run."""
    return ["ai", f"ai:{responsibility}"] if responsibility else ["ai"]


def partition_key(tenant_id: str, scope: str, start: date) -> str:
    return f"{KEY_PREFIX}{tenant_id}#{scope}#{start.isoformat()}"


def micro_usd(cost_usd: Any) -> int:
    """Whole millionths of a dollar for a cost in dollars; nothing for a run that priced no call."""
    return int((Decimal(str(cost_usd or 0)) * MICRO).to_integral_value())


@dataclass(frozen=True)
class Spent:
    """What one scope's cycle holds. ``partial`` when some call had no price: the total is then at least ``usd``."""
    microUsd: int
    calls: int
    unpricedCalls: int

    @property
    def usd(self) -> Decimal:
        return Decimal(self.microUsd) / MICRO

    @property
    def partial(self) -> bool:
        return self.unpricedCalls > 0


def history_key(tenant_id: str, responsibility: str) -> str:
    return f"{KEY_PREFIX}{tenant_id}#ai:{responsibility}#{HISTORY_CYCLE}"


def log_micro_usd(cost_usd: Any) -> Decimal:
    """The natural logarithm of a positive cost in millionths of a dollar, to nine places: what the history adds up."""
    return (Decimal(str(cost_usd)) * MICRO).ln().quantize(LOGARITHM_PLACES)


@dataclass(frozen=True)
class CostHistory:
    """An agent's fully priced runs so far, as running sums of the logarithm of each run's cost in millionths of a dollar."""
    runs: int
    sumLogMicroUsd: Decimal
    sumSquaredLogMicroUsd: Decimal


def cost_history(table: Any, *, tenant_id: str, responsibility: str) -> CostHistory:
    """What the agent's history holds now (no runs when nothing was counted)."""
    item = table.get_item(Key={"pk": history_key(tenant_id, responsibility), "sk": HISTORY_SORT_KEY}, ConsistentRead=True).get("Item") or {}
    return CostHistory(int(item.get("runs", 0)), Decimal(str(item.get("sumLogMicroUsd", 0))), Decimal(str(item.get("sumSquaredLogMicroUsd", 0))))


def record_run(table: Any, *, tenant_id: str, responsibility: str | None, run_id: str, period: str, cost_usd: Any, calls: int, unpriced_calls: int,
               moment: datetime, add_to_history: bool = False) -> bool:
    """Add one finished run's cost to its scopes for the cycle that contains ``moment``. True when it was added, False when this run was counted already.
    With ``add_to_history`` (an agent's run whose every call was priced and whose cost is above zero) the run joins the agent's cost history too."""
    if not tenant_id or not run_id:
        raise SpendError("A run is counted for a site and by its run id.")
    start = cycle_start(period, moment)
    stamp = moment.astimezone(timezone.utc).isoformat()
    expires = int((moment + MARKER_LIFETIME).timestamp())
    items: list[dict[str, Any]] = []
    for scope in scopes_of(responsibility):
        key = partition_key(tenant_id, scope, start)
        items.append({"Put": {"TableName": table.name, "Item": {"pk": key, "sk": f"{MARKER_SORT_PREFIX}{run_id}", "ttl": expires},
                              "ConditionExpression": "attribute_not_exists(pk)"}})
        items.append({"Update": {"TableName": table.name, "Key": {"pk": key, "sk": TOTAL_SORT_KEY},
                                 "UpdateExpression": "ADD microUsd :cost, calls :calls, unpricedCalls :unpriced SET updatedAt = :stamp",
                                 "ExpressionAttributeValues": {":cost": micro_usd(cost_usd), ":calls": calls, ":unpriced": unpriced_calls, ":stamp": stamp}}})
    if add_to_history:
        if not responsibility or unpriced_calls or Decimal(str(cost_usd or 0)) <= 0:
            raise SpendError("Only an agent's run with a cost above zero and every call priced joins its cost history.")
        logarithm = log_micro_usd(cost_usd)
        items.append({"Update": {"TableName": table.name, "Key": {"pk": history_key(tenant_id, responsibility), "sk": HISTORY_SORT_KEY},
                                 "UpdateExpression": "ADD runs :one, sumLogMicroUsd :log, sumSquaredLogMicroUsd :squared SET updatedAt = :stamp",
                                 "ExpressionAttributeValues": {":one": 1, ":log": logarithm, ":squared": (logarithm * logarithm).quantize(LOGARITHM_PLACES),
                                                               ":stamp": stamp}}})
    try:
        table.meta.client.transact_write_items(TransactItems=items)
    except Exception as error:   # a botocore ClientError; read by its response so this module needs no AWS library to be imported
        response = getattr(error, "response", None)
        if not isinstance(response, dict):
            raise
        reasons = response.get("CancellationReasons") or []
        if response.get("Error", {}).get("Code") == "TransactionCanceledException" and any(r.get("Code") == "ConditionalCheckFailed" for r in reasons):
            return False   # the marker of this run is already there: its cost was added when the wake was first delivered
        raise SpendError(f"The spend of run {run_id} could not be added to the ledger: {error}") from error
    return True


def spent(table: Any, *, tenant_id: str, scope: str, period: str, moment: datetime) -> Spent:
    """What a scope's cycle holds now (zero when nothing was counted)."""
    return spent_in(table, tenant_id=tenant_id, scope=scope, start=cycle_start(period, moment))


def spent_in(table: Any, *, tenant_id: str, scope: str, start: date) -> Spent:
    """What a scope holds for the cycle that starts on ``start`` (a cycle whose start is not a period's, such as X's billing cycle). Zero when nothing was counted."""
    item = table.get_item(Key={"pk": partition_key(tenant_id, scope, start), "sk": TOTAL_SORT_KEY}, ConsistentRead=True).get("Item") or {}
    return Spent(int(item.get("microUsd", 0)), int(item.get("calls", 0)), int(item.get("unpricedCalls", 0)))


def add_charge(table: Any, *, tenant_id: str, scope: str, start: date, amount: Any, moment: datetime) -> Spent:
    """Add one charge to a scope for the cycle that starts on ``start``, atomically, and return what the cycle then holds. No marker: Caducus reports each charge once
    (it holds the delivery's own attempt log), so a charge has no run id to be counted by."""
    if not tenant_id:
        raise SpendError("A charge is counted for a site.")
    try:
        answer = table.update_item(
            Key={"pk": partition_key(tenant_id, scope, start), "sk": TOTAL_SORT_KEY},
            UpdateExpression="ADD microUsd :cost, calls :one SET updatedAt = :stamp",
            ExpressionAttributeValues={":cost": micro_usd(amount), ":one": 1, ":stamp": moment.astimezone(timezone.utc).isoformat()},
            ReturnValues="ALL_NEW")
    except Exception as error:
        raise SpendError(f"A charge could not be added to the ledger: {error}") from error
    item = answer.get("Attributes") or {}
    return Spent(int(item.get("microUsd", 0)), int(item.get("calls", 0)), int(item.get("unpricedCalls", 0)))


HALT_PREFIX = f"{KEY_PREFIX}HALT#"
HALT_SORT_KEY = "HALT"
EVERY_SITE = "ALL"


def halt_key(tenant_id: str | None) -> str:
    return f"{HALT_PREFIX}{tenant_id or EVERY_SITE}"


def halt_reason(table: Any, tenant_id: str | None) -> str | None:
    """Why runs are halted for this site, or None. A halt row for every site stops every run; a halt row for one site stops that site's."""
    for key in dict.fromkeys([halt_key(None), halt_key(tenant_id)] if tenant_id else [halt_key(None)]):
        item = table.get_item(Key={"pk": key, "sk": HALT_SORT_KEY}, ConsistentRead=True).get("Item")
        if item:
            return str(item.get("reason") or "no reason was recorded")
    return None


def set_halt(table: Any, *, tenant_id: str | None, reason: str, by: str, moment: datetime) -> None:
    """The kill switch: from now no run starts for the site (or for every site when ``tenant_id`` is None) until ``clear_halt``."""
    if not reason.strip() or not by.strip():
        raise SpendError("A halt says why and who set it.")
    table.put_item(Item={"pk": halt_key(tenant_id), "sk": HALT_SORT_KEY, "reason": reason.strip(), "by": by.strip(), "at": moment.astimezone(timezone.utc).isoformat()})


def clear_halt(table: Any, *, tenant_id: str | None) -> None:
    table.delete_item(Key={"pk": halt_key(tenant_id), "sk": HALT_SORT_KEY})
