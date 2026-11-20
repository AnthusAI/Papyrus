from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.newsletter.manage import apply_unsubscribe  # noqa: E402
from papyrus_content.notifications import migration  # noqa: E402
from papyrus_content.notifications.migration_test import UNTIL, Move, moving, run_cli  # noqa: E402


def _close(context) -> None:
    manager = getattr(context, "move_manager", None)
    if manager is not None:
        manager.__exit__(None, None, None)
        context.move_manager = None


def _move(context) -> Move:
    return context.move


def _held(context, address: str) -> list[str]:
    return _move(context).held(address)


@given('a site whose newsletter has the lists "weekly" (the roundup), "alerts-a" and "alerts-b", moving to notifications with the same lists')
def site(context) -> None:
    context.move_manager = moving()
    context.move = context.move_manager.__enter__()
    context.add_cleanup(_close, context)
    context.result = None


@given('"{address}" confirmed "{first}" and "{second}" on the newsletter')
def confirmed_two(context, address: str, first: str, second: str) -> None:
    _move(context).join(address, [first, second])


@given('"{address}" confirmed "{list_id}" on the newsletter')
def confirmed_one(context, address: str, list_id: str) -> None:
    _move(context).join(address, [list_id])


@given('three readers confirmed "{first}" and "{second}" on the newsletter')
def three_readers(context, first: str, second: str) -> None:
    for number in range(3):
        _move(context).join(f"group{number}@example.com", [first, second])


@given('"{address}" confirmed "{list_id}" and then bounced')
def bounced(context, address: str, list_id: str) -> None:
    _move(context).join(address, [list_id])
    _move(context).bounce(address)


@given('"{address}" confirmed "{list_id}" and was suppressed by hand')
def suppressed_by_hand(context, address: str, list_id: str) -> None:
    _move(context).join(address, [list_id])
    _move(context).suppress_manually(address)


@given('"{address}" confirmed "{list_id}" and then unsubscribed from everything')
def confirmed_then_left(context, address: str, list_id: str) -> None:
    _move(context).join(address, [list_id])
    _move(context).unsubscribe(address)


@given('"{address}" asked for "{list_id}" and never confirmed')
def asked_only(context, address: str, list_id: str) -> None:
    _move(context).request_only(address, [list_id])


@given('the notifications settings declare only "{list_id}"')
def declare_only(context, list_id: str) -> None:
    _move(context).declared = [list_id]


@given("the migration ran")
@when("the migration runs")
def migration_runs(context) -> None:
    context.result = _move(context).apply()


@when("the migration runs again")
def migration_runs_again(context) -> None:
    context.table_after_first = _move(context).table()
    context.result = _move(context).apply()


@when("the dry run prints")
def dry_run(context) -> None:
    context.plan = _move(context).plan()
    context.printed = migration.render_plan(context.plan)


@when("the migration is asked to run")
def asked_to_run(context) -> None:
    context.table_before = _move(context).table()
    context.refused = None
    try:
        _move(context).apply(context.plan)
    except migration.Refused as problem:
        context.refused = str(problem)


@when("the migration is verified")
def verified(context) -> None:
    context.verification = _move(context).verify()


@given('"{address}" turned "{list_id}" off on the newsletter')
def turned_off(context, address: str, list_id: str) -> None:
    move = _move(context)
    apply_unsubscribe(move.source.service, move.source.hid(address), [list_id], f"unsubscribed:{list_id}")


@given('"{address}" unsubscribed from everything on the newsletter')
def left(context, address: str) -> None:
    _move(context).unsubscribe(address)


@given('"{address}" deleted their data with the old manage link')
def deleted(context, address: str) -> None:
    answer = _move(context).site.act("delete_subscriber", token=_move(context).old_token(address))
    assert answer["body"]["status"] == "deleted", answer


@when('"{address}" opens the manage link from an old email')
def opens_old_link(context, address: str) -> None:
    context.state = _move(context).site.act("preferences_state", token=_move(context).old_token(address))


@when('they use the unsubscribe link for "{list_id}" from an old email')
def old_unsubscribe(context, list_id: str) -> None:
    move = _move(context)
    assert move.site.act("unsubscribe", token=move.old_token("reader@example.com"), list=list_id)["body"]["status"] == "unsubscribed"


@when("the day after the old-link date has passed")
def after_the_date(context) -> None:
    clock = _move(context).site.clock
    clock.now = datetime.fromtimestamp(UNTIL + 1, tz=timezone.utc)


@when('the story "{title}" is published in the "{section}" section and mailed')
def published(context, title: str, section: str) -> None:
    site = _move(context).site
    site.publish(title, section)
    site.play_queue()


@when("the command is run without the freeze statement")
def command_without_freeze(context) -> None:
    context.table_before = _move(context).table()
    context.stopped = False
    try:
        run_cli(_move(context), "run", "--newsletter-table", "newsletter")
    except SystemExit:
        context.stopped = True


@when('the command runs with the freeze statement and the date "{day}"')
def command_runs(context, day: str) -> None:
    context.exit_code, context.printed_output = run_cli(_move(context), "run", "--newsletter-table", "newsletter", "--sends-frozen", "--old-links-until", day)
    assert context.exit_code == 0, context.printed_output


@when("the command verifies")
def command_verifies(context) -> None:
    context.exit_code, context.printed_output = run_cli(_move(context), "verify", "--newsletter-table", "newsletter")


@then('"{address}" is subscribed to "{list_id}" in notifications')
def subscribed(context, address: str, list_id: str) -> None:
    assert list_id in _held(context, address), _held(context, address)


@then('"{address}" is subscribed only to "{list_id}" in notifications')
def subscribed_only(context, address: str, list_id: str) -> None:
    assert _held(context, address) == [list_id], _held(context, address)


@then('"{address}" is subscribed to nothing in notifications')
def subscribed_to_nothing(context, address: str) -> None:
    assert _held(context, address) == [], _held(context, address)


@then("their consent evidence is the original, marked migrated")
def evidence(context) -> None:
    move = _move(context)
    original = move.source.profile("reader@example.com")["consent"]
    (record,) = move.consent_records("reader@example.com")
    assert record["source"] == "migrated" and record["from"] == "newsletter"
    assert {name: record[name] for name in original} == original


@then("no mail of any kind was sent")
def no_mail(context) -> None:
    site = _move(context).site
    assert site.mailer.calls == [] and site.queues.sent == []


@then('it counts {confirmed:d} confirmed on "{list_id}" and {other:d} confirmed on "{other_list}"')
def counts(context, confirmed: int, list_id: str, other: int, other_list: str) -> None:
    assert context.plan.per_list[list_id]["confirmed"] == confirmed and context.plan.per_list[other_list]["confirmed"] == other, context.plan.per_list


@then("it counts {suppressed:d} bounce suppression and {records:d} consent records with evidence")
def counts_suppressed(context, suppressed: int, records: int) -> None:
    assert context.plan.suppressed == {"bounce": suppressed}, context.plan.suppressed
    assert context.plan.consent["with_evidence"] == records and context.plan.consent["without_evidence"] == 0, context.plan.consent


@then("it shows the suppressed address masked, never in full")
def masked(context) -> None:
    assert "b***@example.com" in context.printed and "bounced@example.com" not in context.printed


@then("every count per list, suppressed address, consent record and old link matches the source")
def matches(context) -> None:
    report = context.verification
    assert report.ok, report.as_dict()
    assert report.suppressed["source"] == report.suppressed["target"] == 1
    assert report.consent["source"] == report.consent["target"] == 5 and report.aliases["source"] == report.aliases["target"] == 5
    assert all(row["source"] == row["target"] and row["source"] > 0 for row in report.per_list.values())


@then("the second run imported nobody and found both unchanged")
def second_run(context) -> None:
    assert (context.result.imported, context.result.unchanged, context.result.settled) == (0, 2, 0), context.result.as_dict()


@then("the notifications table is exactly what it was after the first run")
def same_table(context) -> None:
    assert _move(context).table() == context.table_after_first


@then('the preferences show "{first}" and "{second}" on')
def preferences(context, first: str, second: str) -> None:
    body = context.state["body"]
    assert body["status"] == "ready" and {entry["id"] for entry in body["lists"] if entry["subscribed"]} == {first, second}, body


@then("the manage link from an old email is invalid")
def invalid_manage(context) -> None:
    answer = _move(context).site.act("preferences_state", token=_move(context).old_token("reader@example.com"))
    assert answer["statusCode"] == 400, answer


@then("the confirm link from an old email is invalid")
def invalid_confirm(context) -> None:
    answer = _move(context).site.act("confirm", token=_move(context).old_token("reader@example.com"))
    assert answer["statusCode"] == 400, answer


@then('the mail goes only to "{address}"')
def story_reaches(context, address: str) -> None:
    assert [call["to"] for call in _move(context).site.mailer.calls] == [address], _move(context).site.mailer.calls


@then("it carries {carried:d} subscriber and does not carry {pending:d} pending and {gone:d} unsubscribed")
def carries(context, carried: int, pending: int, gone: int) -> None:
    plan = context.plan
    assert len(plan.carried) == carried and plan.not_carried == {"pending": pending, "unsubscribed": gone}, plan.as_dict()


@then('it reports the problem "{problem}"')
def reports_problem(context, problem: str) -> None:
    assert problem in context.plan.problems and problem in context.printed, context.plan.problems


@then("it is refused and the notifications table is unchanged")
def refused(context) -> None:
    assert context.refused and _move(context).table() == context.table_before


@then('Caducus refused "{masked_address}" and "{address}" is subscribed to nothing in notifications')
def refused_erased(context, masked_address: str, address: str) -> None:
    assert context.result.refused == [masked_address], context.result.as_dict()
    assert _held(context, address) == []


@then("it stops and nothing was written")
def stops(context) -> None:
    assert context.stopped and _move(context).table() == context.table_before


@then("it reports that every count matches")
def command_matches(context) -> None:
    assert context.exit_code == 0 and "every count matches" in context.printed_output, context.printed_output
