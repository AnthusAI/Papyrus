"""GA4 events and location redaction: what the emitted scripts send, run in node."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from papyrus_content.markus_renderer.consent import ConsentModeSettings
from papyrus_content.markus_renderer.docs_site import DocsSiteConfig, build_docs_site
from test_markus_docs_site import write_documentation_tree
from papyrus_content.markus_renderer.shell import NavItem, SiteChrome, render_page

MEASUREMENT_ID = "G-ABC123DEF4"
HAS_NODE = shutil.which("node") is not None
PLUGIN_SCRIPT = Path(__file__).parents[3] / "src/papyrus_content/projection/plugin_assets/papyrus-newsletter-pages.js"
FORM_SCRIPT = Path(__file__).parents[3] / "src/papyrus_content/projection/standard/assets/papyrus-form.js"


def render(**chrome: object) -> str:
    return render_page(
        title="T",
        fragment="<p>Home.</p>",
        active_href="index.html",
        nav_items=[NavItem("Home", "index.html")],
        chrome=SiteChrome(site_name="Demo", **chrome),
    )


class AnalyticsOffByDefaultTests(unittest.TestCase):
    def test_a_page_without_a_measurement_id_has_no_analytics_output(self) -> None:
        page = render()
        for fragment in ("gtag", "papyrusAnalytics", "dataLayer", "googletagmanager"):
            self.assertNotIn(fragment, page)

    def test_a_measurement_id_adds_the_redaction_before_the_loader_and_the_events_script(self) -> None:
        page = render(ga_measurement_id=MEASUREMENT_ID, consent_mode=ConsentModeSettings())
        self.assertLess(page.index("page_location"), page.index("googletagmanager.com/gtag/js"))
        self.assertIn("window.papyrusAnalytics", page)


NODE_EVENTS_HARNESS = r"""
const html = require('fs').readFileSync(0, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const state = JSON.parse(process.argv[1]);
global.window = global;
const listeners = {};
global.document = { referrer: state.referrer || '', addEventListener: (type, h) => { listeners[type] = h; } };
global.location = new URL(state.url || 'https://site.example/page/');
global.localStorage = { getItem: () => null, setItem() {} };
const events = [];
const redactionAndEvents = scripts.filter((s) => s.includes('page_location') || s.includes('papyrusAnalytics'));
const redaction = redactionAndEvents.find((s) => s.includes('page_location'));
const eventScript = redactionAndEvents.find((s) => s.includes('papyrusAnalytics'));
new Function(redaction)();
const setCommand = Array.from(window.dataLayer[0]);
global.gtag = (...args) => events.push(args);
new Function(eventScript)();
for (const call of state.calls || []) window.papyrusAnalytics.track(call[0], call[1]);
for (const click of state.clicks || []) {
  const anchor = {
    href: click.href,
    textContent: click.text,
    getAttribute: (name) => (name === 'data-cta-location' ? (click.location ?? null) : null),
    closest: (selector) => (selector.includes('data-promotion-id') && click.sponsor ? {} : null),
  };
  listeners.click({ target: { closest: () => anchor } });
}
console.log(JSON.stringify({ setCommand, events }));
"""


def run_events(**state: object) -> dict:
    page = render(ga_measurement_id=MEASUREMENT_ID, consent_mode=ConsentModeSettings())
    done = subprocess.run(
        ["node", "-e", NODE_EVENTS_HARNESS, json.dumps(state)], input=page, capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


@unittest.skipUnless(HAS_NODE, "node is required to execute the emitted scripts")
class LocationRedactionTests(unittest.TestCase):
    def location(self, url: str, referrer: str = "") -> dict:
        return run_events(url=url, referrer=referrer)["setCommand"][1]

    def test_identity_query_parameters_tokens_and_the_fragment_are_removed(self) -> None:
        sent = self.location(
            "https://site.example/newsletter/confirmed/?token=abc&lists=weekly&utm_source=x&email=a%40b.example&ss=ss1_abcdef#frag"
        )
        self.assertEqual(sent["page_location"], "https://site.example/newsletter/confirmed/?lists=weekly&utm_source=x")

    def test_a_value_that_looks_like_an_opaque_token_or_subject_is_removed_whatever_its_name(self) -> None:
        sent = self.location("https://site.example/p/?ref=" + "a" * 40 + "&who=ss1_zzz&ok=yes")
        self.assertEqual(sent["page_location"], "https://site.example/p/?ok=yes")

    def test_subjects_and_addresses_in_the_path_are_replaced(self) -> None:
        sent = self.location("https://site.example/u/ss1_abc123/home/")
        self.assertEqual(sent["page_location"], "https://site.example/u/redacted/home/")

    def test_the_referrer_is_redacted_the_same_way(self) -> None:
        sent = self.location("https://site.example/", referrer="https://other.example/x?token=1&q=2")
        self.assertEqual(sent["page_referrer"], "https://other.example/x?q=2")

    def test_the_set_command_is_an_arguments_object_gtag_can_read(self) -> None:
        self.assertEqual(run_events()["setCommand"][0], "set")


@unittest.skipUnless(HAS_NODE, "node is required to execute the emitted scripts")
class EventTests(unittest.TestCase):
    def test_a_marked_link_reports_cta_click_with_host_and_path_only(self) -> None:
        events = run_events(
            clicks=[
                {
                    "href": "https://anth.us/engage/?solution=Shipped&cta=hero&token=abc",
                    "text": "  Talk to us →",
                    "location": "hero",
                }
            ]
        )["events"]
        self.assertEqual(
            events,
            [["event", "cta_click", {"cta_text": "Talk to us", "cta_location": "hero", "link_url": "anth.us/engage/", "transport_type": "beacon"}]],
        )

    def test_a_link_to_the_anthus_engage_form_reports_cta_click_with_its_cta_value_as_the_place(self) -> None:
        events = run_events(
            clicks=[{"href": "https://anth.us/engage/?solution=Demo&cta=footer", "text": "Contact us"}]
        )["events"]
        self.assertEqual(events[0][2]["cta_location"], "footer")
        self.assertEqual(events[0][2]["link_url"], "anth.us/engage/")

    def test_other_unmarked_links_report_nothing(self) -> None:
        self.assertEqual(run_events(clicks=[{"href": "https://github.com/AnthusAI/x", "text": "GitHub"}])["events"], [])
        self.assertEqual(run_events(clicks=[{"href": "https://evil.example/engage/?cta=x", "text": "x"}])["events"], [])

    def test_an_unsafe_location_label_becomes_page(self) -> None:
        events = run_events(clicks=[{"href": "https://x.example/a", "text": "Go", "location": "Hero Banner!"}])["events"]
        self.assertEqual(events[0][2]["cta_location"], "page")

    def test_a_sponsor_unit_never_reports_cta_click(self) -> None:
        self.assertEqual(run_events(clicks=[{"href": "https://x.example/a", "text": "Go", "location": "hero", "sponsor": True}])["events"], [])

    def test_only_reserved_events_and_listed_parameters_are_sent(self) -> None:
        events = run_events(
            calls=[
                ["page_view", {"a": 1}],
                ["sign_up", {"method": "newsletter", "user_id": "u1", "email": "a@b.example"}],
                ["generate_lead", {"form_id": "contact", "lead_source": "direct#hero"}],
                ["view_promotion", {"promotion_id": "p1", "creative_name": "c1", "user_id": "u"}],
                ["select_promotion", {"promotion_id": "p1"}],
                ["hasOwnProperty", {}],
            ]
        )["events"]
        self.assertEqual(
            events,
            [
                ["event", "sign_up", {"method": "newsletter"}],
                ["event", "generate_lead", {"form_id": "contact", "lead_source": "direct#hero"}],
                ["event", "view_promotion", {"promotion_id": "p1", "creative_name": "c1"}],
                ["event", "select_promotion", {"promotion_id": "p1"}],
            ],
        )

    def test_identity_looking_values_are_dropped(self) -> None:
        events = run_events(
            calls=[["generate_lead", {"form_id": "reader@example.org", "lead_source": "ss1_abc", "solution": "Shipped"}]]
        )["events"]
        self.assertEqual(events, [["event", "generate_lead", {"solution": "Shipped"}]])

    def test_link_urls_lose_scheme_query_and_fragment(self) -> None:
        events = run_events(calls=[["cta_click", {"cta_text": "x", "cta_location": "nav", "link_url": "https://a.example/b?token=1#c"}]])["events"]
        self.assertEqual(events[0][2]["link_url"], "a.example/b")


@unittest.skipUnless(shutil.which("markus"), "markus executable not installed")
class DocsSiteAnalyticsTests(unittest.TestCase):
    def build(self, **config: object) -> str:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_documentation_tree(root / "docs")
            build_docs_site(DocsSiteConfig("Demo", "tag", root / "docs", "https://x", **config), root / "out")
            return (root / "out" / "index.html").read_text(encoding="utf-8")

    def test_default_docs_sites_have_no_analytics(self) -> None:
        page = self.build()
        self.assertNotIn("gtag", page)
        self.assertNotIn("Cookie settings", page)

    def test_a_measurement_id_turns_on_consent_mode_the_banner_the_footer_link_and_the_privacy_link(self) -> None:
        page = self.build(ga_measurement_id=MEASUREMENT_ID)
        self.assertIn("gtag('consent','default'", page)
        self.assertIn('id="papyrus-consent-banner"', page)
        self.assertIn('<a href="#" data-papyrus-consent-reopen hidden>Cookie settings</a>', page)
        self.assertIn('href="https://anth.us/privacy/"', page)
        self.assertLess(page.index("consent','default'"), page.index("googletagmanager.com/gtag/js"))


class FormConversionConfigTests(unittest.TestCase):
    def test_a_form_names_its_conversion_event_and_nothing_else_is_accepted(self) -> None:
        from papyrus_content.projection.standard.config import FormField, FormSpec
        from papyrus_content.projection.standard.forms import render_form

        spec = FormSpec("contact", "Contact", (FormField("email", "Email", "email"),), endpoint="/api/f", conversion_event="generate_lead")
        self.assertIn('data-analytics-event="generate_lead"', render_form(spec))
        plain = FormSpec("contact", "Contact", (FormField("email", "Email", "email"),), endpoint="/api/f")
        self.assertNotIn("data-analytics-event", render_form(plain))

    def test_an_unknown_conversion_event_is_rejected(self) -> None:
        from papyrus_content.projection.standard.config import _conversion_event

        self.assertEqual(_conversion_event("generate_lead", "f"), "generate_lead")
        with self.assertRaises(ValueError):
            _conversion_event("sign_up", "f")


class BrowserScriptTests(unittest.TestCase):
    def test_the_newsletter_confirmed_page_reports_sign_up_once_and_only_with_a_token(self) -> None:
        source = PLUGIN_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('window.papyrusAnalytics.track("sign_up", { method: "newsletter" })', source)
        self.assertRegex(source, r"confirmed: function \(root, query\) \{[^}]*reportSignUpOnce\(query\.get\(\"token\"\)")
        self.assertIn("TOKEN.test(token)", source)
        self.assertNotIn("sign_up", source.split("var pages = {")[1].split("unsubscribe:")[0].replace('reportSignUpOnce(query.get("token") || "")', ""))

    def test_the_form_script_reports_generate_lead_only_inside_the_success_branch(self) -> None:
        source = FORM_SCRIPT.read_text(encoding="utf-8")
        success = source.index("if (response.ok) {")
        failure = source.index("else { say(form.dataset.failure, true); }")
        self.assertLess(success, source.index('"generate_lead"'))
        self.assertLess(source.index('"generate_lead"'), failure)
        self.assertEqual(source.count("papyrusAnalytics"), 2)  # guard + call, both in the success branch
        self.assertNotRegex(source.split("addEventListener(\"submit\"")[1].split("fetch(")[0], r"papyrusAnalytics")


if __name__ == "__main__":
    unittest.main()
