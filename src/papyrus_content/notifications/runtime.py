"""Assembling Caducus's collaborators for one site, with the site's own renderer.

``assemble`` takes the stores and clients as arguments so specs and tests run on the package's in-memory fakes;
``build_runtime`` creates the real AWS ones from the function environment. Both give the same ``Runtime``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import formataddr
from typing import Any, Callable, Mapping

from caducus.notify.audience import AudienceDirectory, AudienceKeys, DnsDomainChecker, DomainChecker, PublicAudience
from caducus.notify.catalog import Catalog, load_host_catalog
from caducus.notify.channels.email import EmailChannel, Mailer, Pacer, SesMailer
from caducus.notify.channels.x import Guard, Http, PriceTable, TokenProvider, UrllibHttp, XChannel
from caducus.notify.delivery_log import DeliveryLog
from caducus.notify.directory import Directory, SsmDirectory
from caducus.notify.grouping import Dispatcher
from caducus.notify.incidents import IncidentTracker
from caducus.notify.kinds import load_registry
from caducus.notify.queues import Queues, SqsQueues
from caducus.notify.routing import Router
from caducus.notify.store import DynamoStore, Store
from caducus.notify.triage import TriageSettings

from papyrus_content.announcements.caducus_x import RECENT_POSTS_READ, CaducusBroadcaster, SettingsPrices, SiteAccounts
from papyrus_content.newsletter.postal import PostalAddress

from .legacy_links import LegacyLinks
from .public import audience_settings
from .renderer import ThemedRenderer
from .sending import SiteEmailChannel, SiteMailer
from .settings import Settings

#: Where ``notification-kinds.json`` (the plugin's own kinds) ships inside the bundle.
#: How long one request to X may take (the same as the account connection's own calls).
X_HTTP_TIMEOUT_SECONDS = 20
CONFIG_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


@dataclass
class XWiring:
    """What the ``x`` channel needs from the host (Caducus's contract, ``caducus.notify.channels.x``): the account connection's status (the site's one connected account), the token provider,
    the guard (pause and budget), the price table and the transport. ``http`` and ``base_url`` are X's; a spec points them at a server on localhost."""

    connection: Callable[[], Mapping[str, Any]]
    tokens: TokenProvider
    guard: Guard
    prices: PriceTable | SettingsPrices
    http: Http
    base_url: str = "https://api.x.com"
    recent_count: int = RECENT_POSTS_READ


@dataclass
class Runtime:
    settings: Settings
    store: Store
    router: Router
    catalog: Catalog
    email: EmailChannel
    log: DeliveryLog
    read_item: Callable[[str], Mapping[str, Any] | None]
    audience: PublicAudience
    keys: AudienceKeys
    #: Old newsletter links, only while the migration's alias period runs (``legacy_links.py``; deleted after).
    legacy: LegacyLinks | None = None
    #: An address's recipient key in this site's table (the migration tool names its rows by it).
    recipient_key: Callable[[str], str] = lambda address: address
    #: Caducus's ``x`` channel and the broadcaster over it, only where the site is wired for X (``XWiring``); None otherwise, and an event for X is then refused as having no audience.
    x: XChannel | None = None
    broadcaster: CaducusBroadcaster | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def assemble(
    settings: Settings,
    *,
    store: Store,
    queues: Queues,
    directory: Directory,
    mailer: Mailer,
    read_item: Callable[[str], Mapping[str, Any] | None],
    clock: Callable[[], datetime] = utcnow,
    retention_days: int = 90,
    pacer: Pacer | None = None,
    postal_address: Callable[[], str | None] = lambda: None,
    key_secret: str,
    domains: DomainChecker,
    unsuppress: Callable[[str], None] | None = None,
    legacy_token_key: bytes | None = None,
    x: XWiring | None = None,
) -> Runtime:
    """``key_secret`` is the site's recipient-key secret (the SSM SecureString the directory also reads)."""
    kinds = load_registry(CONFIG_DIRECTORY)
    catalog = load_host_catalog(CONFIG_DIRECTORY)
    log = DeliveryLog(store, clock, retention_days)
    readers = AudienceDirectory(SiteAccounts(x.connection, directory) if x is not None else directory)
    # The audience raises its confirmation through the router, and the router fans public kinds out over the audience.
    audience_keys = AudienceKeys.from_secret(key_secret)
    audience = PublicAudience(
        store,
        audience_settings(settings, unsuppress),
        audience_keys,
        domains,
        clock,
        lambda detail: router.handle_detail(detail),
    )
    readers.audience = audience
    router = Router(
        store=store,
        kinds=kinds,
        log=log,
        directory=readers,
        audience=audience,
        fanout_queues=queues,
        dispatcher=Dispatcher(store, log, queues, kinds, clock),
        incidents=IncidentTracker(store, clock),
        catalog=catalog,
        triage=TriageSettings(portal_url="", role_name="", accounts={}, sites={}),
        clock=clock,
    )
    email = SiteEmailChannel(
        store,
        log,
        readers,
        SiteMailer(mailer, settings.site_id, settings.configuration_set),
        postal_address=postal_address,
        pacer=pacer,
        renderer=ThemedRenderer(settings),
        audience=audience,
    )
    x_channel = broadcaster = None
    if x is not None:
        x_channel = XChannel(store, log, readers, tokens=x.tokens, prices=x.prices, guard=x.guard, clock=clock, http=x.http, recent_count=x.recent_count, base_url=x.base_url)
        broadcaster = CaducusBroadcaster(router, log, x_channel, settings.site_id, clock)
    return Runtime(
        x=x_channel, broadcaster=broadcaster,
        settings=settings, store=store, router=router, catalog=catalog, email=email, log=log, read_item=read_item, audience=audience, keys=audience_keys,
        recipient_key=audience_keys.recipient,
        legacy=LegacyLinks(legacy_token_key, audience, lambda: clock().timestamp()) if legacy_token_key else None,
    )


def published_item_reader() -> Callable[[str], Mapping[str, Any] | None]:
    def read(published_item_id: str) -> Mapping[str, Any] | None:
        from papyrus_content.graphql_authoring import create_authoring_client

        return create_authoring_client()[0].get_record("PublishedItem", published_item_id)

    return read


def build_runtime(environment: Mapping[str, str] = os.environ) -> Runtime:
    import boto3

    settings = Settings.from_environment(environment)
    ssm = boto3.client("ssm")
    sesv2 = boto3.client("sesv2")
    mailer = SesMailer(sesv2, formataddr((settings.from_name, settings.from_address)), settings.configuration_set)
    key_secret = ssm.get_parameter(Name=environment["RECIPIENT_KEY_PARAMETER"], WithDecryption=True)["Parameter"]["Value"]

    legacy_token_key = None
    if settings.legacy_newsletter_key_parameter:
        from papyrus_content.newsletter.keys import derive_keys

        legacy_secret = ssm.get_parameter(Name=settings.legacy_newsletter_key_parameter, WithDecryption=True)["Parameter"]["Value"]
        legacy_token_key = derive_keys(legacy_secret).token

    def unsuppress(address: str) -> None:
        """A reader lifted a bounce or complaint by opting in again: clear the SES account suppression list too."""
        try:
            sesv2.delete_suppressed_destination(EmailAddress=address)
        except sesv2.exceptions.NotFoundException:
            pass
    return assemble(
        settings,
        store=DynamoStore(boto3.resource("dynamodb").Table(environment["TABLE_NAME"])),
        queues=SqsQueues(boto3.client("sqs"), {"email": environment["EMAIL_QUEUE_URL"], **({"x": environment["X_QUEUE_URL"]} if environment.get("X_QUEUE_URL") else {})}),
        directory=SsmDirectory(ssm, environment["OPERATORS_PARAMETER"], environment["RECIPIENT_KEY_PARAMETER"]),
        mailer=mailer,
        read_item=published_item_reader(),
        retention_days=int(environment.get("RETENTION_DAYS", "90")),
        pacer=Pacer(mailer.max_send_rate),
        postal_address=PostalAddress(settings.site_id, ssm).resolve,
        key_secret=key_secret,
        domains=DnsDomainChecker(),
        unsuppress=unsuppress,
        legacy_token_key=legacy_token_key,
        x=x_wiring(environment, ssm) if environment.get("X_QUEUE_URL") else None,
    )


def x_wiring(environment: Mapping[str, str], ssm: Any) -> XWiring:
    """The site's X connection, token provider, guard and price table, read from the stores of the ``announcements`` function (its two model tables, the spend counter and the SSM
    parameters). The consumer has no signed-in person, so it reads them directly with its own role, as that function does."""
    import time

    import boto3

    from papyrus_content.announcements.channel import CaducusTokens
    from papyrus_content.announcements.guard import SpendGuard
    from papyrus_content.announcements.settings import AnnouncementSettings
    from papyrus_content.announcements.stores import DynamoConnection, DynamoSettings, DynamoSpendLedger, SsmParameters
    from papyrus_content.announcements.x_account import XAccounts, XEndpoints

    dynamodb = boto3.resource("dynamodb")
    announcement_settings = AnnouncementSettings(DynamoSettings(dynamodb.Table(environment["ANNOUNCEMENT_SETTINGS_TABLE"]), time.time), time.time)
    accounts = XAccounts(
        site_id=environment["SITE_ID"],
        endpoints=XEndpoints(authorize_url=environment["X_AUTHORIZE_URL"], token_url=environment["X_TOKEN_URL"], revoke_url=environment["X_REVOKE_URL"], api_base=environment["X_API_BASE"]),
        parameters=SsmParameters(ssm), connection=DynamoConnection(dynamodb.Table(environment["X_CONNECTION_TABLE"]), time.time), pauses=announcement_settings,
        lease_seconds=float(environment["X_REFRESH_LEASE_SECONDS"]),
    )
    return XWiring(
        connection=accounts.status, tokens=CaducusTokens(accounts), guard=SpendGuard(DynamoSpendLedger(dynamodb.Table(environment["ANNOUNCEMENT_SPEND_TABLE"]), time.time), announcement_settings),
        prices=SettingsPrices(announcement_settings.read), http=UrllibHttp(timeout=X_HTTP_TIMEOUT_SECONDS), base_url=environment["X_API_BASE"],
    )


def x_broadcaster(environment: Mapping[str, str] = os.environ) -> CaducusBroadcaster | None:
    """The site's Broadcaster over Caducus's ``x`` channel, or None where the site's config does not provide one (no ``X_QUEUE_URL``): X is then not wired and a site set to On refuses to run
    (``announcements.x_delivery``)."""
    return build_runtime(environment).broadcaster if environment.get("X_QUEUE_URL") else None


_RUNTIME: Runtime | None = None


def runtime() -> Runtime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = build_runtime()
    return _RUNTIME
