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

CONSENT_DENIED_BY_DEFAULT_REGIONS: tuple[str, ...] = (
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "IS", "LI", "NO", "GB", "CH",
)

CONSENT_REOPEN_ATTRIBUTE = "data-papyrus-consent-reopen"
CONSENT_BANNER_ELEMENT_ID = "papyrus-consent-banner"
CONSENT_REOPEN_FUNCTION_NAME = "papyrusOpenConsentChoices"


@dataclass(frozen=True)
class ConsentModeSettings:
    denied_by_default_regions: tuple[str, ...] = CONSENT_DENIED_BY_DEFAULT_REGIONS
    wait_for_update_milliseconds: int = 500
    policy_version: int = 1
    retention_days: int = 183
    banner_heading: str = "Cookies and analytics"
    banner_message: str = (
        "We use cookies to measure how this site is used and, if you agree, "
        "for advertising. You can accept all, reject all, and change your "
        "choice at any time."
    )
    accept_label: str = "Accept all"
    reject_label: str = "Reject all"
    banner_region_label: str = "Cookie consent"
    privacy_policy_url: str | None = None
    privacy_policy_label: str = "Privacy policy"

    def __post_init__(self) -> None:
        regions = tuple(self.denied_by_default_regions)
        object.__setattr__(self, "denied_by_default_regions", regions)
        for region in regions:
            if not isinstance(region, str) or not _CONSENT_REGION_PATTERN.fullmatch(region):
                raise ValueError(
                    f"consent region must be an ISO 3166 code like 'DE' or 'US-CA', got {region!r}"
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
    if "denied_by_default_regions" in values:
        values["denied_by_default_regions"] = tuple(values["denied_by_default_regions"])
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


def render_consent_defaults_script(settings: ConsentModeSettings, *, site_name: str) -> str:
    wait = settings.wait_for_update_milliseconds
    regional_default = ""
    if settings.denied_by_default_regions:
        regional_default = (
            "gtag('consent','default',{ad_storage:'denied',ad_user_data:'denied',"
            "ad_personalization:'denied',analytics_storage:'denied',"
            f"wait_for_update:{wait},"
            f"region:{_javascript_literal(list(settings.denied_by_default_regions))}}});\n"
        )
    return (
        regional_default
        + "gtag('consent','default',{ad_storage:'denied',ad_user_data:'denied',"
        f"ad_personalization:'denied',analytics_storage:'granted',wait_for_update:{wait}}});\n"
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
        "c.apply=function(granted){var v=granted?'granted':'denied';"
        "gtag('consent','update',{ad_storage:v,ad_user_data:v,ad_personalization:v,analytics_storage:v})};\n"
        "c.save=function(granted){try{localStorage.setItem(c.key,JSON.stringify("
        "{version:c.version,savedAt:Date.now(),granted:granted}))}catch(e){}};\n"
        "var stored=c.read();if(stored)c.apply(stored.granted)})();\n"
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
        f"var r=document.querySelectorAll('[{CONSENT_REOPEN_ATTRIBUTE}]');"
        "c.openChoices=function(){b.hidden=false;var f=b.querySelector('button');if(f)f.focus()};"
        f"window.{CONSENT_REOPEN_FUNCTION_NAME}=c.openChoices;"
        "b.addEventListener('click',function(e){"
        "var t=e.target.closest('[data-papyrus-consent-choice]');if(!t)return;"
        "var g=t.getAttribute('data-papyrus-consent-choice')==='accept';"
        "c.apply(g);c.save(g);b.hidden=true});"
        "for(var i=0;i<r.length;i++){r[i].hidden=false;"
        "r[i].addEventListener('click',function(e){e.preventDefault();c.openChoices()})}"
        "if(!c.read())b.hidden=false})();</script>"
    )
