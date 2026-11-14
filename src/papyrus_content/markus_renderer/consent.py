"""Opt-in Google Consent Mode v2 and first-party consent banner for Markus pages.

Design rules (the rationale is in the pull request that introduced this module):

* Nothing here runs unless a publication sets ``SiteChrome.consent_mode``.
* The default consent state is decided by gtag's region-scoped ``default``
  commands. Client-side region guessing is never used.
* The banner is first-party, has no external dependency and no focus trap.
  Accept and Reject share one class and therefore one visual weight.
* All configured text is plain text and is HTML-escaped on output.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields

_CONSENT_REGION_PATTERN = re.compile(r"[A-Z]{2}(?:-[A-Z0-9]{1,3})?")
_CONSENT_SAFE_URL_PATTERN = re.compile(r"(?:https?://|/(?!/))[^\s\"'<>]*")

MILLISECONDS_PER_DAY = 86_400_000

# POLICY CHOICE, NOT LEGAL ADVICE. This is the default list of regions where a visitor must be asked before analytics
# or advertising cookies are used: the EU 27, the other EEA states (IS, LI, NO), the United Kingdom (GB) and
# Switzerland (CH), as ISO 3166-1 alpha-2 codes. Which regions need a notice is a decision that the site owner (or
# their legal adviser) owns; it changes as laws change and it must be reviewed, not trusted. A site replaces it with
# ``denied_by_default_regions`` or extends it with ``additional_denied_by_default_regions``. This is the single
# definition: the browser script, the Google ``region`` parameter and the edge function generator all read it.
CONSENT_DENIED_BY_DEFAULT_REGIONS: tuple[str, ...] = (
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "IS", "LI", "NO", "GB", "CH",
)

DEFAULT_REGION_LOOKUP_ADDRESS = "/_papyrus/consent"
DEFAULT_REGION_LOOKUP_TIMEOUT_MILLISECONDS = 1500
_REGION_LOOKUP_ADDRESS_PATTERN = re.compile(r"/(?!/)[A-Za-z0-9._~!$&()*+,;=:@%/-]*")
_COUNTRY_PATTERN = re.compile(r"[A-Z]{2}")

CONSENT_REOPEN_ATTRIBUTE = "data-papyrus-consent-reopen"
CONSENT_BANNER_ELEMENT_ID = "papyrus-consent-banner"
CONSENT_REOPEN_HREF = "#cookie-settings"  # a footer link in settings (no attributes needed) reopens the choices
CONSENT_REOPEN_FUNCTION_NAME = "papyrusOpenConsentChoices"


DEFAULT_BANNER_MESSAGE = (
    "We use cookies to measure how this site is used and, if you agree, "
    "for advertising. You can accept all, reject all, and change your "
    "choice at any time."
)
ANALYTICS_ONLY_BANNER_MESSAGE = (
    "We use cookies to measure how this site is used. We do not use them for advertising. "
    "You can accept all, reject all, and change your choice at any time."
)


@dataclass(frozen=True)
class ConsentModeSettings:
    denied_by_default_regions: tuple[str, ...] = CONSENT_DENIED_BY_DEFAULT_REGIONS
    wait_for_update_milliseconds: int = 500
    policy_version: int = 1
    retention_days: int = 183
    banner_heading: str = "Cookies and analytics"
    banner_message: str = DEFAULT_BANNER_MESSAGE
    accept_label: str = "Accept all"
    reject_label: str = "Reject all"
    banner_region_label: str = "Cookie consent"
    privacy_policy_url: str | None = None
    privacy_policy_label: str = "Privacy policy"
    region_lookup: bool = False
    """Off by default: the banner then shows to everyone without a stored choice, exactly as before. When true the page
    asks ``region_lookup_address`` once, and only a visitor outside the notice regions skips the banner."""
    region_lookup_address: str = DEFAULT_REGION_LOOKUP_ADDRESS
    region_lookup_timeout_milliseconds: int = DEFAULT_REGION_LOOKUP_TIMEOUT_MILLISECONDS
    additional_denied_by_default_regions: tuple[str, ...] = ()
    """Regions added to ``denied_by_default_regions`` (which replaces the shipped list when given)."""
    analytics_only: bool = False
    """Off by default. When true, Accept grants only ``analytics_storage``: ``ad_storage``, ``ad_user_data`` and
    ``ad_personalization`` stay denied after every choice, and the default banner text does not mention advertising."""

    def __post_init__(self) -> None:
        if not isinstance(self.analytics_only, bool):
            raise ValueError(f"consent analytics_only must be true or false, got {self.analytics_only!r}")
        if self.analytics_only and self.banner_message == DEFAULT_BANNER_MESSAGE:
            object.__setattr__(self, "banner_message", ANALYTICS_ONLY_BANNER_MESSAGE)
        for name in ("region_lookup",):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"consent {name} must be true or false, got {getattr(self, name)!r}")
        if not isinstance(self.region_lookup_address, str) or not _REGION_LOOKUP_ADDRESS_PATTERN.fullmatch(
            self.region_lookup_address
        ):
            raise ValueError(
                "consent region_lookup_address must be a site-absolute path like '/_papyrus/consent', "
                f"got {self.region_lookup_address!r}"
            )
        timeout = self.region_lookup_timeout_milliseconds
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 100 <= timeout <= 10_000:
            raise ValueError(
                f"consent region_lookup_timeout_milliseconds must be between 100 and 10000, got {timeout!r}"
            )
        added = tuple(self.additional_denied_by_default_regions)
        regions = tuple(dict.fromkeys(tuple(self.denied_by_default_regions) + added))
        object.__setattr__(self, "additional_denied_by_default_regions", added)
        object.__setattr__(self, "denied_by_default_regions", regions)
        for region in regions:
            if not isinstance(region, str) or not _CONSENT_REGION_PATTERN.fullmatch(region):
                raise ValueError(
                    f"consent region must be an ISO 3166 code like 'DE' or 'US-CA', got {region!r}"
                )
        if self.region_lookup:
            for region in regions:
                if not _COUNTRY_PATTERN.fullmatch(region):
                    raise ValueError(
                        "consent region_lookup decides by country, so every notice region must be a two-letter "
                        f"country code, got {region!r}"
                    )
        for name in ("wait_for_update_milliseconds", "policy_version", "retention_days"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"consent {name} must be a non-negative integer, got {value!r}")
        if self.policy_version < 1 or self.retention_days < 1:
            raise ValueError("consent policy_version and retention_days must be at least 1")
        for name in (
            "banner_heading",
            "banner_message",
            "accept_label",
            "reject_label",
            "banner_region_label",
            "privacy_policy_label",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"consent {name} must be a non-empty string")
        if self.privacy_policy_url is not None and not _CONSENT_SAFE_URL_PATTERN.fullmatch(
            self.privacy_policy_url
        ):
            raise ValueError(
                "consent privacy_policy_url must be an http(s) URL or a site-absolute path, "
                f"got {self.privacy_policy_url!r}"
            )


def consent_mode_from_mapping(raw: Mapping[str, object]) -> ConsentModeSettings:
    known = {field.name for field in fields(ConsentModeSettings)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"Unknown consent_mode settings: {', '.join(sorted(unknown))}")
    values = dict(raw)
    for list_name in ("denied_by_default_regions", "additional_denied_by_default_regions"):
        if list_name in values:
            if isinstance(values[list_name], (str, bytes)) or not isinstance(values[list_name], (list, tuple)):
                raise ValueError(f"consent {list_name} must be a list of region codes")
            values[list_name] = tuple(values[list_name])
    return ConsentModeSettings(**values)


def consent_storage_key(site_name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "", site_name.lower()) or "site"
    return f"{key}-consent"


def _javascript_literal(value: object) -> str:
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


# The decision, as a pure function of the edge answer. The notice is skipped only for an answer that says, in so many
# words, ``notice: false`` for a two-letter country. Anything else (no answer, a string, an array, a missing or empty
# country, ``notice`` absent or not a boolean) needs the notice: the site fails closed.
CONSENT_NOTICE_DECISION_JS = (
    "function(a){return!(a&&typeof a==='object'&&a.notice===false"
    "&&typeof a.country==='string'&&/^[A-Z]{2}$/.test(a.country))}"
)


def render_region_lookup_script(settings: ConsentModeSettings) -> str:
    """Runs inside the defaults script, after ``c.read``. Asks the site's own edge address once, only with no stored
    choice, never waits for it, and never stores, logs or forwards the answer."""
    return (
        f"c.needsNotice={CONSENT_NOTICE_DECISION_JS};\n"
        "c.lookup=!stored;c.notice=null;c.showNotice=null;\n"
        "c.settle=function(a){if(c.notice!==null)return;c.notice=c.needsNotice(a);"
        "if(c.notice){if(c.showNotice)c.showNotice();return}"
        "if(c.read())return;"  # a choice made while the lookup was pending always wins
        "gtag('consent','update',{analytics_storage:'granted'})};\n"
        "if(c.lookup){try{var k=new AbortController(),"
        f"t=setTimeout(function(){{c.settle(null);k.abort()}},{settings.region_lookup_timeout_milliseconds});"
        f"fetch({_javascript_literal(settings.region_lookup_address)},"
        "{method:'GET',credentials:'omit',cache:'no-store',referrer:'',referrerPolicy:'no-referrer',"
        "headers:{accept:'application/json'},signal:k.signal})"
        ".then(function(r){if(!r.ok)throw 0;return r.json()})"
        ".then(function(a){clearTimeout(t);c.settle(a)},function(){clearTimeout(t);c.settle(null)})}"
        "catch(e){c.settle(null)}}\n"
    )


def render_consent_defaults_script(settings: ConsentModeSettings, *, site_name: str) -> str:
    wait = settings.wait_for_update_milliseconds
    regional_default = ""
    # With the lookup on, the global default below already denies everything (fail closed), so the region-scoped
    # default would repeat it; without the lookup the region-scoped default is what protects regulated visitors.
    if settings.denied_by_default_regions and not settings.region_lookup:
        regional_default = (
            "gtag('consent','default',{ad_storage:'denied',ad_user_data:'denied',"
            "ad_personalization:'denied',analytics_storage:'denied',"
            f"wait_for_update:{wait},"
            f"region:{_javascript_literal(list(settings.denied_by_default_regions))}}});\n"
        )
    return (
        regional_default
        + "gtag('consent','default',{ad_storage:'denied',ad_user_data:'denied',"
        f"ad_personalization:'denied',analytics_storage:'{'denied' if settings.region_lookup else 'granted'}',"
        f"wait_for_update:{wait}}});\n"
        "gtag('set','ads_data_redaction',true);\n"
        "gtag('set','url_passthrough',false);\n"
        "(function(){var c=window.papyrusConsent={"
        f"key:{_javascript_literal(consent_storage_key(site_name))},"
        f"version:{settings.policy_version},"
        f"retentionMilliseconds:{settings.retention_days * MILLISECONDS_PER_DAY}}};\n"
        "c.read=function(){try{var s=JSON.parse(localStorage.getItem(c.key));"
        "if(s&&s.version===c.version&&typeof s.savedAt==='number'&&typeof s.granted==='boolean'"
        "&&s.savedAt<=Date.now()&&Date.now()-s.savedAt<c.retentionMilliseconds)return s}"
        "catch(e){}return null};\n"
        + (
            "c.apply=function(granted){var v=granted?'granted':'denied';"
            "gtag('consent','update',{ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied',analytics_storage:v})};\n"
            if settings.analytics_only
            else "c.apply=function(granted){var v=granted?'granted':'denied';"
            "gtag('consent','update',{ad_storage:v,ad_user_data:v,ad_personalization:v,analytics_storage:v})};\n"
        )
        +
        "c.save=function(granted){try{localStorage.setItem(c.key,JSON.stringify("
        "{version:c.version,savedAt:Date.now(),granted:granted}))}catch(e){}};\n"
        "var stored=c.read();if(stored)c.apply(stored.granted);\n"
        + (render_region_lookup_script(settings) if settings.region_lookup else "")
        + "})();\n"
    )


CONSENT_BANNER_STYLE = (
    "<style>\n"
    ".papyrus-consent{position:fixed;left:0;right:0;bottom:0;z-index:2147483000;"
    "box-sizing:border-box;max-width:44rem;margin:1rem;padding:1rem 1.25rem;"
    "background:Canvas;color:CanvasText;border:2px solid CanvasText;border-radius:.5rem;"
    "font:1rem/1.45 system-ui,sans-serif}\n"
    ".papyrus-consent[hidden]{display:none}\n"
    ".papyrus-consent h2{margin:0 0 .5rem;font-size:1.125rem}\n"
    ".papyrus-consent p{margin:0 0 1rem}\n"
    ".papyrus-consent-actions{display:flex;flex-wrap:wrap;gap:.75rem}\n"
    ".papyrus-consent-choice{flex:1 1 9rem;min-height:2.75rem;padding:.5rem 1rem;"
    "font:inherit;font-weight:600;color:CanvasText;background:Canvas;"
    "border:2px solid CanvasText;border-radius:.375rem;cursor:pointer}\n"
    ".papyrus-consent-choice:hover{background:CanvasText;color:Canvas}\n"
    ".papyrus-consent-choice:focus-visible,.papyrus-consent a:focus-visible"
    "{outline:3px solid Highlight;outline-offset:2px}\n"
    "</style>"
)


def render_consent_banner(settings: ConsentModeSettings) -> str:
    policy_link = ""
    if settings.privacy_policy_url is not None:
        policy_link = (
            f' <a href="{html.escape(settings.privacy_policy_url, quote=True)}">'
            f"{html.escape(settings.privacy_policy_label)}</a>"
        )
    return (
        f'<div id="{CONSENT_BANNER_ELEMENT_ID}" class="papyrus-consent" role="region" '
        f'aria-label="{html.escape(settings.banner_region_label, quote=True)}" '
        'aria-describedby="papyrus-consent-message" hidden>\n'
        f'<h2 id="papyrus-consent-heading">{html.escape(settings.banner_heading)}</h2>\n'
        f'<p id="papyrus-consent-message">{html.escape(settings.banner_message)}{policy_link}</p>\n'
        '<div class="papyrus-consent-actions">\n'
        '<button type="button" class="papyrus-consent-choice" data-papyrus-consent-choice="reject">'
        f"{html.escape(settings.reject_label)}</button>\n"
        '<button type="button" class="papyrus-consent-choice" data-papyrus-consent-choice="accept">'
        f"{html.escape(settings.accept_label)}</button>\n"
        "</div>\n"
        "</div>\n"
        "<script>(function(){var c=window.papyrusConsent;"
        f"var b=document.getElementById({_javascript_literal(CONSENT_BANNER_ELEMENT_ID)});"
        "if(!c||!b)return;"
        f"var r=document.querySelectorAll('[{CONSENT_REOPEN_ATTRIBUTE}],a[href=\"{CONSENT_REOPEN_HREF}\"]');"
        "c.openChoices=function(){b.hidden=false;var f=b.querySelector('button');if(f)f.focus()};"
        f"window.{CONSENT_REOPEN_FUNCTION_NAME}=c.openChoices;"
        "b.addEventListener('click',function(e){"
        "var t=e.target.closest('[data-papyrus-consent-choice]');if(!t)return;"
        "var g=t.getAttribute('data-papyrus-consent-choice')==='accept';"
        "c.apply(g);c.save(g);b.hidden=true});"
        "for(var i=0;i<r.length;i++){r[i].hidden=false;"
        "r[i].addEventListener('click',function(e){e.preventDefault();c.openChoices()})}"
        + (
            "if(!c.read()){if(c.lookup){c.showNotice=function(){if(!c.read())b.hidden=false};"
            "if(c.notice===true)c.showNotice()}else b.hidden=false}})();</script>"
            if settings.region_lookup
            else "if(!c.read())b.hidden=false})();</script>"
        )
    )
