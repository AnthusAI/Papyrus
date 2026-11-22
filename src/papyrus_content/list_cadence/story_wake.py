"""What the announce agent does when a Story's page goes live or its rating changes (PPY-e3bb2b, design section 13.3 change A).

Two facts start an Announcement, and both are changes to the Story's own record, so the Item change feed (``item_change_feed.py``) delivers them as wakes through the
site's wake queue and nothing else does:

``stage_entered`` with ``stage=published``
    **The record that marks "the page is live" is the Story's Item row entering the ``published`` stage.** ``publish_item`` writes that stage on the Item in the same
    update that makes the version the lineage's current one, so the change feed sees it whoever published (the console, the command line, an agent, a scheduled
    publish). Nothing else is written for the feed's sake: a publish writes only its own records, so its latency does not change. The page's files are projected
    after that write, within seconds, by the projection the publish started or its scheduled retry. An Announcement is a decision, and its Delivery waits for its
    release time, its review and its send, so the worker does not hand a reader a link before the page serves it by being quick. The worker still checks the
    ``PublishedItem`` row (the published copy the pages are made from) before it decides anything, so a Story that was unpublished since the wake is not announced.
``rated``
    The Story's star rating was set, changed or cleared in place. A Story that qualifies only after a person rates it is announced at that moment.

A wake only says that something happened. The worker **re-reads the Story and re-checks everything** as it is now: that the page is live, the Story's rating, the lists'
rules and the site policy's rung. It decides from those and never from the wake, so a late, duplicated or out-of-order wake changes nothing it should not. What it makes
is the same either way (``announce.announce_story``): one Announcement, whose once-only key is ``story-published:<lineage>``, and one email Delivery for the every-item
lists that carry the Story. A second wake for the same Story (a republish, a rating changed again, a stream record delivered twice, a retry after a crash) finds that
Announcement and makes no second one. A rating change on a Story that was already announced is therefore harmless, and a rating change on a Story that did not qualify
before is what makes it eligible.

The wake key is ``<agent>|<lineage>|<version>|<what>`` (``wake_keys.py``): the run record made from it is the claim, so a redelivered wake starts no second run, and
the once-only key is the second line of defence for the decision itself. The agent runs one wake at a time (``serialBy: agent`` in its definition), because every wake
may spend from one account's budget and write to one account's Deliveries.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Callable, Collection, Mapping

from papyrus_content.announcements.decisions import Announcements
from papyrus_content.announcements.link_reads import StoryRef
from papyrus_content.announcements.records import EMAIL, RecordError
from papyrus_content.announcements.x_announce import XAnnouncer, XServices
from papyrus_content.run_outcomes import OUTCOME_KEY, REASON_KEY

from .alert_text import alert_drafter, alert_facts
from .announce import STORY_PUBLISHED, Candidate, Drafter, Result
from .store import ListState
from .wake import run_story_change

AGENT = RESPONSIBILITY = "announce"
#: The Announcement's ``trigger`` words: what started the decision that made it.
PAGE_LIVE, RATING_CHANGED = "page_live", "rating_changed"
#: Why a run made nothing, as the run record's reason code.
NOT_LIVE_CODE, TRANSLATION_CODE = "story_not_published", "story_is_translation"
PUBLISHED = "published"
CHANGE_STAGE_ENTERED, CHANGE_RATED = "stage_entered", "rated"
TENANT_ENVIRONMENT, BUCKET_ENVIRONMENT = "PAPYRUS_TENANT_ID", "PAPYRUS_SITE_BUCKET"


class StoryWakeError(ValueError):
    """A wake that is not a Story's page going live or its rating changing, or a run that cannot be set up. Nothing is made."""


@dataclass(frozen=True)
class StoryWake:
    lineage: str
    version: str
    change: str
    trigger: str


def story_wake(request: Mapping[str, Any]) -> StoryWake:
    """What the wake says happened, and nothing more. A wake for another change or another stage is refused: a definition that listens for one is mistaken."""
    given = request.get("input") or {}
    lineage, version, change = given.get("story"), given.get("version"), given.get("change")
    if not lineage or not version:
        raise StoryWakeError("The wake names no Story and version: the announce agent is woken by a change to a Story.")
    if change == CHANGE_STAGE_ENTERED and given.get("stage") == PUBLISHED:
        return StoryWake(str(lineage), str(version), change, PAGE_LIVE)
    if change == CHANGE_RATED:
        return StoryWake(str(lineage), str(version), change, RATING_CHANGED)
    raise StoryWakeError(f"The announce agent is woken when a Story enters the published stage or its rating changes; this wake is {change!r} ({given.get('what')!r}).")


def not_live(lineage: str) -> Result:
    return Result(None, f"Story {lineage} is not published now, so nothing is announced", code=NOT_LIVE_CODE)


def run_story_wake(request: Mapping[str, Any], state: ListState, announcements: Announcements, *, read_story: Callable[[str], Candidate | None], draft: Drafter,
                   policy_rung: Callable[[str], str], account_id: str, by: str = AGENT, now: str | None = None, x: XAnnouncer | None = None,
                   edit_settings: Mapping[str, Any] | Callable[[], Mapping[str, Any]] | None = None) -> Result:
    """One wake. ``read_story(lineage)`` reads the Story as it is now: its published copy and its rating, or None when the page is not live. The wake's own words are
    used only to say which of the two things happened.

    ``x`` is the X part (``x_announce.XAnnouncer``), None where the site has none wired. It asks whether the Story qualifies on X now (a site with X off is asked nothing it
    can act on), and the Delivery it builds is written with the Announcement in the same call, or added to the Announcement an earlier wake made. ``edit_settings`` is the
    announcement settings document, whose edit windows give each Delivery its release and lock times."""
    found = story_wake(request)
    candidate = read_story(found.lineage)
    if candidate is None:
        return not_live(found.lineage)
    if candidate.translation:
        return Result(None, f"Story {found.lineage} is a translation, not a new Story: its readers were told when the original published", code=TRANSLATION_CODE)
    considered = x.consider(found.lineage) if x is not None else None
    result = run_story_change(candidate, state, announcements, draft=draft, policy_rung=policy_rung, account_id=account_id, by=by, now=now, trigger=found.trigger,
                              extra_plans=considered.plans if considered else (), edit_settings=edit_settings)
    if x is None or considered is None:
        return result
    notes, worked = x.finished(considered, result.outcome, now=now)
    return replace(result, notes=tuple(notes), worked=worked)


# --- the procedure's tool: the real services ----------------------------------------------------------------------------------------------------------


@dataclass
class Services:
    """Everything the run reaches outside itself for. A test replaces each one."""

    state: Callable[[], ListState]
    announcements: Announcements
    read_story: Callable[[str], Candidate | None]
    draft: Drafter
    account_id: str
    #: The X part (None: this site's run has none). ``stamps`` reads whether a person reviewed a Story's source.
    x: XServices | None = None
    stamps: Any = None
    #: The announcement settings document, whose edit windows give each Delivery its release and lock times.
    edit_settings: Callable[[], Mapping[str, Any]] = lambda: {}
    #: The deliver step for X: ``now -> the Deliveries sent`` (``announcements.x_delivery.send_due`` over the site's Broadcaster). None where the site has no X part. It raises
    #: ``ChannelNotAvailable`` when the site is set to On and has no Caducus ``x`` channel wired.
    send_x: Callable[[str | None], list[dict[str, Any]]] | None = None
    #: The deliver step for email: ``now -> the Deliveries handed to Caducus`` (``announcements.email_delivery.send_due_email``). None where the site has no email queue.
    send_email: Callable[[str | None], list[dict[str, Any]]] | None = None


def read_candidate(client: Any, lineage: str, issue_types: Collection[str] = ()) -> Candidate | None:
    """The Story as a list's rule sees it, read now: the published copy (the pages are made from it) and the rating on the lineage's current record. None when the
    Story is not published. ``issue_types`` are the Story types of the site's issue Stories, which no list announces."""
    from papyrus_content.announcements.intake import ChecklistReviewStamps
    from papyrus_content.item_front_matter import front_matter
    from papyrus_content.item_language import localization_original
    from papyrus_content.item_stars import effective_rating
    from .alert_text import tags_of
    from papyrus_content.publishing import published_item_id_for

    published = client.get_record("PublishedItem", published_item_id_for(lineage))
    if not published or published.get("status") != PUBLISHED:
        return None
    head = next((row for row in client.list_by_index("itemsByLineageAndVersion", lineage) if row.get("versionState") == "current" and row.get("stage") == PUBLISHED), None)
    if head is None:
        return None
    version = int(published.get("versionNumber") or 1)
    return Candidate(story=StoryRef(lineage, head["id"], version), section=published.get("section") or None, story_type=published.get("type"), issue=published.get("type") in issue_types,
                     tags=tags_of(front_matter(published)), stars=int(effective_rating(head)["stars"]),
                     reviewed_source=ChecklistReviewStamps(client).reviewed(lineage, version), translation=localization_original(published, getattr(client, "tenant_id", None)) is not None)


def issue_types_of(document: Mapping[str, Any]) -> set[str]:
    """The Story types the site's lists write their issue Stories as."""
    return {entry["issueType"] for entry in document["lists"].values() if entry.get("issueType")}


def default_services(environ: Mapping[str, str]) -> Services:
    """The services of a real run. The site's own store and sending account are named by the runner's environment (``procedure_runner.child_environment``); a run that
    does not have them stops, and never guesses where a site's settings are. The email channel's one sending account is the site's own, named by its tenant."""
    import boto3

    from papyrus_content.agent_policy.run_gate import SiteCatalogue
    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.site_store import SiteStore

    from .store import ListSettingsStore

    tenant, bucket = (environ.get(TENANT_ENVIRONMENT) or "").strip(), (environ.get(BUCKET_ENVIRONMENT) or "").strip()
    if not tenant or not bucket:
        raise StoryWakeError(f"The announce agent needs the site's tenant and bucket ({TENANT_ENVIRONMENT} and {BUCKET_ENVIRONMENT}) from the runner, so it can read the lists' settings.")
    client, _ = create_authoring_client()
    settings = ListSettingsStore(SiteStore(boto3.client("s3"), bucket, SiteCatalogue(client)))

    from papyrus_content.announcements.deliveries import Deliveries
    from papyrus_content.announcements.eligibility import load_story
    from papyrus_content.announcements.handlers import ORIGIN_ENV, STYLE_ENV, Functions, x_services
    from papyrus_content.announcements.intake import ChecklistReviewStamps

    def origin() -> str:
        value = (environ.get(ORIGIN_ENV) or "").strip()
        if not value:
            raise StoryWakeError(f"Set {ORIGIN_ENV} to the site's public address so the alert can link to the Story.")
        return value

    draft = alert_drafter(lambda lineage: load_story(client, lineage, item_url_style=environ.get(STYLE_ENV, "html")), origin)
    functions = Functions(client)
    # Every Delivery this run writes sets its follow-up timer, so a Delivery that may not go yet (its edit window, its review) is sent at its time with nobody looking (deliver_due.py).
    deliveries = Deliveries(client, timers=site_delivery_timers(environ, client))
    announcements = Announcements(client, deliveries)
    send_x, send_email = deliver_steps(client, environ, deliveries, announcements, lists=lambda: settings.read(tenant).document["lists"], functions=functions)
    return Services(state=lambda: settings.read(tenant), announcements=announcements, read_story=lambda lineage: read_candidate(client, lineage, issue_types_of(settings.read(tenant).document)), draft=draft,
                    account_id=tenant, x=x_services(client, environ, model=True, functions=functions), stamps=ChecklistReviewStamps(client), edit_settings=functions.read,
                    send_x=send_x, send_email=send_email)


def site_delivery_timers(environ: Mapping[str, str], client: Any) -> Any:
    """The site's follow-up timers for its Deliveries (``delivery_timers.DeliveryTimers``), named by the runner's environment (``procedure_runner.child_environment``). A run that
    writes Deliveries without them would leave a Delivery that nobody sends at its time, so a run that does not have them stops."""
    from papyrus_content.announcements.delivery_timers import DeliveryTimers
    from papyrus_content.follow_up_timers import SiteNotNamed

    try:
        return DeliveryTimers.from_environment(environ, appsync_endpoint=client.endpoint)
    except SiteNotNamed as missing:
        raise StoryWakeError(str(missing)) from missing


def deliver_steps(client: Any, environ: Mapping[str, str], deliveries: Any, announcements: Announcements, *, lists: Callable[[], Mapping[str, Any]],
                  functions: Any = None) -> tuple[Callable[[str | None], list[dict[str, Any]]], Callable[[str | None], list[dict[str, Any]]]]:
    """The deliver steps of a real run, X then email, over ``deliveries`` (which hold the site's timers): ``now -> the Deliveries handed over``. The announce agent runs them after it
    decides, and the engine's ``deliver_due`` run when a Delivery's time comes. ``lists`` reads the lists' settings, which only the email channel needs."""
    from papyrus_content.announcements.handlers import Functions
    from papyrus_content.announcements.spend import ledger_from_environment
    from papyrus_content.announcements.x_delivery import send_due
    from papyrus_content.announcements.x_runner import SpendControl
    from papyrus_content.announcements.email_channel import CaducusEmail
    from papyrus_content.announcements.email_delivery import send_due_email
    from papyrus_content.notifications.runtime import build_runtime

    functions = functions or Functions(client)
    control = SpendControl(settings=functions, connection=functions.status, ledger=ledger_from_environment(environ))
    # The site's Broadcaster is the one its config provides (the notifications function's X queue); a site without one has None, and a site set to On without it refuses to run.
    wired = build_runtime(environ) if environ.get("EMAIL_QUEUE_URL") else None
    broadcaster = wired.broadcaster if wired is not None else remote_broadcaster(environ)
    # Email goes to Caducus through the router and delivery log of the site's own notifications function; a site without its email queue has no email channel.
    email = CaducusEmail(wired.router, wired.log, wired.settings.site_id, alert_facts, lists=lists()) if wired is not None else None
    return (lambda now: send_due(deliveries, announcements, control, broadcaster, now)), (lambda now: send_due_email(deliveries, email, now))


def remote_broadcaster(environ: Mapping[str, str]) -> Any:
    """In the shared procedure runner, which holds none of the site's Caducus wiring: the site's broadcast function, named by the runner (``X_BROADCAST_FUNCTION``). None elsewhere."""
    from papyrus_content.announcements.remote_broadcaster import ENVIRONMENT, RemoteBroadcaster

    name = (environ.get(ENVIRONMENT) or "").strip()
    return RemoteBroadcaster(name) if name else None


#: The Delivery change feed's change when a person approved a version: the run sends what is due and decides nothing (PPY-1de948).
APPROVED = "approved"


def send_only(services: Services, now: str | None = None) -> dict[str, Any]:
    """A Delivery's approval: send every Delivery that is due (its approval is now in place) and report what went. No Story is read and nothing is decided."""
    sent = services.send_x(now) if services.send_x is not None else []
    emailed = services.send_email(now) if services.send_email is not None else []
    went = [row["id"] for row in sent] + [row["id"] for row in emailed]
    return {"story": "", "x_sent": [row["id"] for row in sent], "email_sent": [row["id"] for row in emailed], "lists": [], "notes": [], "announcement": None, "created": False,
            "summary": f"Sent {len(went)} approved Delivery(ies)." if went else "An approval woke the agent; nothing was due to send.",
            "run_outcome": "acted" if went else "nothing", "run_outcome_reason": "sent" if went else "nothing_due"}


def policy_rung_of(run: Any) -> Callable[[str], str]:
    """The site policy's rung of the announce responsibility for one list's email Deliveries, as the run was started under it (``agent_policy.resolve``)."""
    from papyrus_content.agent_policy.resolve import effective

    def rung(list_id: str) -> str:
        return effective(run.policy, RESPONSIBILITY, {"channel": EMAIL, "kind": STORY_PUBLISHED, "list": list_id}).rung

    return rung


def announce_story(story: str, version: str, change: str, what: str = "", stage: str = "", environ: Mapping[str, str] | None = None, services: Services | None = None,
                   now: str | None = None) -> dict[str, Any]:
    """The procedure's work for one wake: re-read the Story and decide. Returns the run's output, with ``run_outcome`` and ``run_outcome_reason`` for the runner."""
    from papyrus_content.agent_gate.run_context import from_environment

    environment = os.environ if environ is None else environ
    run = from_environment(environment)
    if run is None or run.responsibility != RESPONSIBILITY:
        raise StoryWakeError('The announce agent runs only on an agent\'s wake, adopted as the responsibility "announce": it needs the policy the runner read for the run.')
    services = services or default_services(environment)
    if change == APPROVED or not story:
        return send_only(services, now)
    request = {"input": {"story": story, "version": version, "change": change, "what": what, "stage": stage or None}}
    x = XAnnouncer(services.x, services.announcements, run.policy, services.stamps) if services.x is not None else None
    try:
        result = run_story_wake(request, services.state(), services.announcements, read_story=services.read_story, draft=services.draft,
                                policy_rung=policy_rung_of(run), account_id=services.account_id, now=now, x=x, edit_settings=services.edit_settings)
    except RecordError as error:
        raise StoryWakeError(str(error)) from error
    declared = result.declaration()
    sent = services.send_x(now) if services.send_x is not None else []
    emailed = services.send_email(now) if services.send_email is not None else []
    return {"story": story, "x_sent": [row["id"] for row in sent], "email_sent": [row["id"] for row in emailed], "summary": result.reason + (" (" + "; ".join(result.notes) + ")" if result.notes else ""), "lists": list(result.list_ids), "notes": list(result.notes), "announcement": result.outcome.announcement["id"] if result.outcome else None,
            "created": bool(result.outcome and result.outcome.created), "run_outcome": declared.get(OUTCOME_KEY, "acted"), "run_outcome_reason": declared.get(REASON_KEY, "announced")}
