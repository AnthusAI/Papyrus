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
from caducus.notify.delivery_log import DeliveryLog
from caducus.notify.directory import Directory, SsmDirectory
from caducus.notify.grouping import Dispatcher
from caducus.notify.incidents import IncidentTracker
from caducus.notify.kinds import load_registry
from caducus.notify.queues import Queues, SqsQueues
from caducus.notify.routing import Router
from caducus.notify.store import DynamoStore, Store
from caducus.notify.triage import TriageSettings

from papyrus_content.newsletter.postal import PostalAddress

from .public import audience_settings
from .renderer import ThemedRenderer
from .sending import SiteEmailChannel, SiteMailer
from .settings import Settings

#: Where ``notification-kinds.json`` (the plugin's own kinds) ships inside the bundle.
CONFIG_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


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
) -> Runtime:
    """``key_secret`` is the site's recipient-key secret (the SSM SecureString the directory also reads)."""
    kinds = load_registry(CONFIG_DIRECTORY)
    catalog = load_host_catalog(CONFIG_DIRECTORY)
    log = DeliveryLog(store, clock, retention_days)
    readers = AudienceDirectory(directory)
    # The audience raises its confirmation through the router, and the router fans public kinds out over the audience.
    audience = PublicAudience(
        store,
        audience_settings(settings, unsuppress),
        AudienceKeys.from_secret(key_secret),
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
    return Runtime(
        settings=settings, store=store, router=router, catalog=catalog, email=email, log=log, read_item=read_item, audience=audience
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

    def unsuppress(address: str) -> None:
        """A reader lifted a bounce or complaint by opting in again: clear the SES account suppression list too."""
        try:
            sesv2.delete_suppressed_destination(EmailAddress=address)
        except sesv2.exceptions.NotFoundException:
            pass
    return assemble(
        settings,
        store=DynamoStore(boto3.resource("dynamodb").Table(environment["TABLE_NAME"])),
        queues=SqsQueues(boto3.client("sqs"), {"email": environment["EMAIL_QUEUE_URL"]}),
        directory=SsmDirectory(ssm, environment["OPERATORS_PARAMETER"], environment["RECIPIENT_KEY_PARAMETER"]),
        mailer=mailer,
        read_item=published_item_reader(),
        retention_days=int(environment.get("RETENTION_DAYS", "90")),
        pacer=Pacer(mailer.max_send_rate),
        postal_address=PostalAddress(settings.site_id, ssm).resolve,
        key_secret=key_secret,
        domains=DnsDomainChecker(),
        unsuppress=unsuppress,
    )


_RUNTIME: Runtime | None = None


def runtime() -> Runtime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = build_runtime()
    return _RUNTIME
