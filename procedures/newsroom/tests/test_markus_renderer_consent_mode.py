from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import unittest

from papyrus_content.markus_renderer.consent import (
    CONSENT_DENIED_BY_DEFAULT_REGIONS,
    ConsentModeSettings,
    consent_mode_from_mapping,
    consent_storage_key,
    render_consent_banner,
)
from papyrus_content.markus_renderer.shell import (
    NavItem,
    SiteChrome,
    render_ga4_snippet,
    render_page,
)
from papyrus_content.projection.projector import settings_from_mapping

MEASUREMENT_ID = "G-ABC123DEF4"
HAS_NODE = shutil.which("node") is not None

EXPECTED_EUROPEAN_REGIONS = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "IS", "LI", "NO", "GB", "CH",
}

GOLDEN_ANALYTICS_SNIPPET_WITHOUT_CONSENT_MODE = (
    '<script async src="https://www.googletagmanager.com/gtag/js?id=G-ABC123DEF4"></script>\n'
    "<script>\n"
    "window.dataLayer = window.dataLayer || [];\n"
    "function gtag(){dataLayer.push(arguments);}\n"
    "gtag('js', new Date());\n"
    'gtag(\'config\', "G-ABC123DEF4");\n'
    "</script>"
)


def _render(chrome: SiteChrome) -> str:
    return render_page(
        title=chrome.site_name,
        fragment="<p>Home.</p>",
        active_href="index.html",
        nav_items=[NavItem("Home", "index.html")],
        chrome=chrome,
    )


def _consent_chrome(**settings: object) -> SiteChrome:
    return SiteChrome(
        site_name="Anth.us",
        ga_measurement_id=MEASUREMENT_ID,
        consent_mode=ConsentModeSettings(**settings),
    )


def _head_script_with_consent(html: str) -> str:
    return re.search(r"<script>\n(window\.dataLayer.*?)</script>", html, re.S).group(1)



class ConsentModeDisabledTests(unittest.TestCase):
    def test_snippet_without_consent_mode_is_byte_identical_to_the_previous_output(self) -> None:
        self.assertEqual(
            render_ga4_snippet(MEASUREMENT_ID), GOLDEN_ANALYTICS_SNIPPET_WITHOUT_CONSENT_MODE
        )
        self.assertEqual(
            render_ga4_snippet(MEASUREMENT_ID, consent_mode=None),
            GOLDEN_ANALYTICS_SNIPPET_WITHOUT_CONSENT_MODE,
        )

    def test_page_without_consent_mode_has_no_consent_output(self) -> None:
        plain = _render(SiteChrome(site_name="S", ga_measurement_id=MEASUREMENT_ID, ga_owner_opt_out=True))
        explicit_none = _render(
            SiteChrome(
                site_name="S", ga_measurement_id=MEASUREMENT_ID, ga_owner_opt_out=True, consent_mode=None
            )
        )
        self.assertEqual(plain, explicit_none)
        for fragment in ("consent", "papyrus-consent", "<style>", "ads_data_redaction"):
            self.assertNotIn(fragment, plain)
        self.assertIn(GOLDEN_ANALYTICS_SNIPPET_WITHOUT_CONSENT_MODE, plain)

    def test_consent_mode_without_measurement_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            _render(SiteChrome(site_name="S", consent_mode=ConsentModeSettings()))


class ConsentDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = _render(_consent_chrome())
        self.script = _head_script_with_consent(self.html)

    def test_defaults_precede_js_and_config(self) -> None:
        defaults = [m.start() for m in re.finditer(r"gtag\('consent','default'", self.script)]
        self.assertEqual(len(defaults), 2)
        self.assertLess(self.script.index("function gtag"), min(defaults))
        self.assertNotIn("gtag('js'", self.script)
        self.assertNotIn("gtag('config'", self.script)
        config = self.html.index("gtag('config'")
        self.assertLess(self.html.index("c.apply(stored.granted)"), config)
        self.assertLess(self.html.index("consent','default'"), config)

    def test_loader_comes_after_consent_defaults_and_before_config(self) -> None:
        loader = self.html.index("googletagmanager.com/gtag/js")
        self.assertLess(self.html.index("consent','default'"), loader)
        self.assertLess(self.html.index("ads_data_redaction"), loader)
        self.assertLess(self.html.index("consent','update'"), loader)
        self.assertLess(self.html.index("function gtag"), loader)
        self.assertLess(loader, self.html.index("gtag('js'"))
        self.assertLess(loader, self.html.index("gtag('config'"))
        self.assertEqual(self.html.count("googletagmanager.com/gtag/js"), 1)

    def test_regional_default_denies_everything_and_global_default_grants_only_analytics(self) -> None:
        regional, general = re.findall(r"gtag\('consent','default',(\{.*?\})\);", self.script)
        self.assertIn("region:", regional)
        for signal in ("ad_storage", "ad_user_data", "ad_personalization", "analytics_storage"):
            self.assertIn(f"{signal}:'denied'", regional)
        self.assertIn("wait_for_update:500", regional)
        self.assertNotIn("region", general)
        self.assertIn("analytics_storage:'granted'", general)
        for signal in ("ad_storage", "ad_user_data", "ad_personalization"):
            self.assertIn(f"{signal}:'denied'", general)

    def test_shipped_region_list_is_eea_plus_uk_and_switzerland(self) -> None:
        regional = re.search(r"region:(\[.*?\])", self.script).group(1)
        self.assertEqual(set(json.loads(regional)), EXPECTED_EUROPEAN_REGIONS)
        self.assertEqual(len(CONSENT_DENIED_BY_DEFAULT_REGIONS), 32)
        self.assertEqual(len(set(CONSENT_DENIED_BY_DEFAULT_REGIONS)), 32)

    def test_ads_data_redaction_on_and_url_passthrough_off(self) -> None:
        self.assertIn("gtag('set','ads_data_redaction',true);", self.script)
        self.assertIn("gtag('set','url_passthrough',false);", self.script)

    def test_site_configured_regions_replace_the_shipped_list(self) -> None:
        script = _head_script_with_consent(
            _render(_consent_chrome(denied_by_default_regions=("DE", "US-CA")))
        )
        self.assertIn('region:["DE", "US-CA"]', script)

    def test_empty_region_list_emits_only_the_global_default(self) -> None:
        script = _head_script_with_consent(_render(_consent_chrome(denied_by_default_regions=())))
        self.assertEqual(script.count("gtag('consent','default'"), 1)

    def test_invalid_region_raises(self) -> None:
        for bad in ("de", "DEU", "D", "DE'];alert(1)//", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ConsentModeSettings(denied_by_default_regions=(bad,))

    def test_owner_opt_out_script_is_unchanged_and_precedes_everything(self) -> None:
        with_consent = _render(
            SiteChrome(
                site_name="Anth.us",
                ga_measurement_id=MEASUREMENT_ID,
                ga_owner_opt_out=True,
                consent_mode=ConsentModeSettings(),
            )
        )
        without_consent = _render(
            SiteChrome(site_name="Anth.us", ga_measurement_id=MEASUREMENT_ID, ga_owner_opt_out=True)
        )
        opt_out = re.search(r"<script>\(function\(\)\{try\{var k=.*?</script>", without_consent).group(0)
        self.assertIn(opt_out, with_consent)
        self.assertLess(with_consent.index("notrack"), with_consent.index("consent','default'"))


class ConsentPersistenceTests(unittest.TestCase):
    def test_storage_key_is_derived_from_site_name(self) -> None:
        self.assertEqual(consent_storage_key("Anth.us"), "anthus-consent")
        self.assertEqual(consent_storage_key("!!!"), "site-consent")
        self.assertIn('key:"anthus-consent"', _render(_consent_chrome()))

    def test_version_and_retention_are_emitted(self) -> None:
        html = _render(_consent_chrome(policy_version=3, retention_days=10))
        self.assertIn("version:3,", html)
        self.assertIn(f"retentionMilliseconds:{10 * 86_400_000}", html)
        self.assertIn(f"retentionMilliseconds:{183 * 86_400_000}", _render(_consent_chrome()))

    def test_invalid_numbers_raise(self) -> None:
        for name, value in (("policy_version", 0), ("retention_days", 0), ("wait_for_update_milliseconds", -1), ("policy_version", True)):
            with self.subTest(name=name, value=value):
                with self.assertRaises(ValueError):
                    ConsentModeSettings(**{name: value})


class ConsentBannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = _render(_consent_chrome())
        self.banner = render_consent_banner(ConsentModeSettings())

    def test_banner_is_labelled_hidden_by_default_and_not_modal(self) -> None:
        self.assertIn('role="region"', self.banner)
        self.assertIn('aria-label="Cookie consent"', self.banner)
        self.assertIn('aria-describedby="papyrus-consent-message"', self.banner)
        self.assertIn(' hidden>', self.banner)
        self.assertNotIn("aria-modal", self.banner)
        self.assertNotIn("dialog", self.banner)
        self.assertNotIn("tabindex", self.banner)
        self.assertNotIn("keydown", self.banner)

    def test_accept_and_reject_are_buttons_with_identical_class(self) -> None:
        buttons = re.findall(r'<button type="button" class="([^"]+)" data-papyrus-consent-choice="(\w+)">(.*?)</button>', self.banner)
        self.assertEqual([(c, k, t) for c, k, t in buttons], [
            ("papyrus-consent-choice", "reject", "Reject all"),
            ("papyrus-consent-choice", "accept", "Accept all"),
        ])
        self.assertEqual(self.banner.count("<button"), 2)

    def test_banner_is_placed_in_body_after_content_and_style_in_head(self) -> None:
        head, body = self.html.split("</head>")
        self.assertIn(".papyrus-consent", head)
        self.assertNotIn("<style>", body)
        self.assertLess(body.index("<footer"), body.index('id="papyrus-consent-banner"'))
        self.assertTrue(body.rstrip().endswith("</script>\n</body>\n</html>"))

    def test_reopen_function_and_footer_link_hook_are_wired(self) -> None:
        self.assertIn("window.papyrusOpenConsentChoices=c.openChoices", self.banner)
        self.assertIn("[data-papyrus-consent-reopen]", self.banner)
        self.assertIn('a[href="#cookie-settings"]', self.banner)
        self.assertIn("e.preventDefault()", self.banner)

    def test_banner_does_not_trap_focus(self) -> None:
        self.assertNotIn("Tab", self.banner)
        self.assertNotIn("focusin", self.banner)

    def test_configured_text_is_escaped(self) -> None:
        hostile = '<script>alert(1)</script>"&\''
        banner = render_consent_banner(
            ConsentModeSettings(
                banner_heading=hostile,
                banner_message=hostile,
                accept_label=hostile,
                reject_label=hostile,
                banner_region_label=hostile,
                privacy_policy_label=hostile,
                privacy_policy_url="https://example.com/p?a=1&b=2",
            )
        )
        self.assertNotIn("<script>alert", banner)
        self.assertEqual(banner.count("&lt;script&gt;alert(1)&lt;/script&gt;"), 6)
        self.assertIn('href="https://example.com/p?a=1&amp;b=2"', banner)

    def test_unsafe_privacy_urls_raise(self) -> None:
        for bad in ("javascript:alert(1)", "//evil.example", 'https://x"onmouseover=1', "data:text/html,x", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ConsentModeSettings(privacy_policy_url=bad)
        ConsentModeSettings(privacy_policy_url="/privacy.html")

    def test_blank_text_raises(self) -> None:
        with self.assertRaises(ValueError):
            ConsentModeSettings(accept_label=" ")

    def test_default_banner_text_is_the_neutral_draft(self) -> None:
        settings = ConsentModeSettings()
        self.assertEqual(settings.banner_heading, "Cookies and analytics")
        self.assertEqual(settings.accept_label, "Accept all")
        self.assertEqual(settings.reject_label, "Reject all")
        self.assertIn(html.escape(settings.banner_message), self.banner)


class ConsentConfigurationTests(unittest.TestCase):
    def test_projection_settings_accept_a_consent_mode_mapping(self) -> None:
        settings = settings_from_mapping(
            {
                "chrome": {
                    "site_name": "Anth.us",
                    "ga_measurement_id": MEASUREMENT_ID,
                    "consent_mode": {"privacy_policy_url": "/privacy.html", "denied_by_default_regions": ["DE"]},
                }
            }
        )
        self.assertEqual(settings.chrome.consent_mode.privacy_policy_url, "/privacy.html")
        self.assertEqual(settings.chrome.consent_mode.denied_by_default_regions, ("DE",))

    def test_empty_mapping_enables_the_shipped_defaults(self) -> None:
        self.assertEqual(consent_mode_from_mapping({}), ConsentModeSettings())

    def test_unknown_consent_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            consent_mode_from_mapping({"banner_title": "x"})


NODE_HARNESS = """
const html = require('fs').readFileSync(0, 'utf8');
const script = [...html.matchAll(/<script>\\n((?:window\\.dataLayer|gtag\\('js')[\\s\\S]*?)<\\/script>/g)].map((m) => m[1]).join('\\n');
const state = JSON.parse(process.argv[1]);
global.window = global;
global.localStorage = {
  data: state.storage || {},
  getItem(k) { return k in this.data ? this.data[k] : null; },
  setItem(k, v) { this.data[k] = v; },
};
if (state.now) { Date.now = () => state.now; }
new Function(script)();
const commands = window.dataLayer.map((a) => Array.from(a));
const result = { commands };
if (state.click) {
  const handlers = [];
  const banner = { hidden: true, addEventListener: (_, h) => handlers.push(h), querySelector: () => null };
  global.document = {
    getElementById: () => banner,
    querySelectorAll: () => [],
  };
  const bannerScript = html.match(/<\\/div>\\n<script>(\\(function[\\s\\S]*?)<\\/script>/)[1];
  new Function(bannerScript)();
  result.shownInitially = banner.hidden === false;
  handlers[0]({ target: { closest: () => ({ getAttribute: () => state.click }) } });
  result.hiddenAfterChoice = banner.hidden === true;
  result.commandsAfter = window.dataLayer.map((a) => Array.from(a));
  result.storage = localStorage.data;
}
console.log(JSON.stringify(result));
"""


@unittest.skipUnless(HAS_NODE, "node is required to execute the emitted consent scripts")
class ConsentRuntimeBehaviourTests(unittest.TestCase):
    def _run(self, **state: object) -> dict:
        html = _render(_consent_chrome())
        completed = subprocess.run(
            ["node", "-e", NODE_HARNESS, json.dumps(state)],
            input=html,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_first_visit_emits_defaults_then_config_and_shows_banner(self) -> None:
        result = self._run(click="accept")
        names = [command[0:2] if command[0] == "consent" else command[0:1] for command in result["commands"]]
        self.assertEqual(
            names,
            [["consent", "default"], ["consent", "default"], ["set"], ["set"], ["js"], ["config"]],
        )
        self.assertTrue(result["shownInitially"])

    def test_accept_updates_all_four_signals_to_granted_and_persists_choice(self) -> None:
        result = self._run(click="accept", now=1_700_000_000_000)
        update = result["commandsAfter"][-1]
        self.assertEqual(update[:2], ["consent", "update"])
        self.assertEqual(
            update[2],
            {"ad_storage": "granted", "ad_user_data": "granted", "ad_personalization": "granted", "analytics_storage": "granted"},
        )
        self.assertTrue(result["hiddenAfterChoice"])
        self.assertEqual(
            json.loads(result["storage"]["anthus-consent"]),
            {"version": 1, "savedAt": 1_700_000_000_000, "granted": True},
        )

    def test_reject_updates_all_four_signals_to_denied(self) -> None:
        result = self._run(click="reject", now=1_700_000_000_000)
        self.assertEqual(
            set(result["commandsAfter"][-1][2].values()), {"denied"}
        )
        self.assertFalse(json.loads(result["storage"]["anthus-consent"])["granted"])

    def _stored(self, **overrides: object) -> str:
        record = {"version": 1, "savedAt": 1_700_000_000_000, "granted": True}
        record.update(overrides)
        return json.dumps(record)

    def test_valid_stored_choice_is_applied_before_config(self) -> None:
        result = self._run(storage={"anthus-consent": self._stored()}, now=1_700_000_000_000 + 1000)
        names = [command[0:2] if command[0] == "consent" else command[0:1] for command in result["commands"]]
        self.assertLess(names.index(["consent", "update"]), names.index(["config"]))

    def test_version_bump_expiry_and_garbage_reprompt(self) -> None:
        now = 1_700_000_000_000
        cases = {
            "other version": self._stored(version=2),
            "expired": self._stored(savedAt=now - 184 * 86_400_000),
            "future": self._stored(savedAt=now + 10_000),
            "not json": "{",
        }
        for label, value in cases.items():
            with self.subTest(label=label):
                result = self._run(storage={"anthus-consent": value}, now=now, click="accept")
                self.assertTrue(result["shownInitially"])
                self.assertNotIn(["consent", "update"], [c[0:2] for c in result["commands"]])

    def test_valid_stored_choice_hides_the_banner(self) -> None:
        now = 1_700_000_000_000
        result = self._run(storage={"anthus-consent": self._stored()}, now=now + 1000, click="reject")
        self.assertFalse(result["shownInitially"])


if __name__ == "__main__":
    unittest.main()
