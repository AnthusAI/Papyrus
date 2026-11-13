"""Region-aware consent: the notice is skipped only when the site's own edge address says it is not needed."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from papyrus_content.markus_renderer.consent import (
    CONSENT_DENIED_BY_DEFAULT_REGIONS,
    ConsentModeSettings,
    consent_mode_from_mapping,
)
from papyrus_content.markus_renderer.shell import NavItem, SiteChrome, render_page
from papyrus_content.projection.projector import settings_from_mapping

MEASUREMENT_ID = "G-ABC123DEF4"
HAS_NODE = shutil.which("node") is not None
ROOT = Path(__file__).resolve().parents[3]

EEA = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT",
    "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO",
}

HARNESS = """
const html = require('fs').readFileSync(0, 'utf8');
const state = JSON.parse(process.argv[1]);
const head = [...html.matchAll(/<script>\\n((?:window\\.dataLayer|gtag\\('js')[\\s\\S]*?)<\\/script>/g)].map((m) => m[1]).join('\\n');
const bannerScript = html.match(/<\\/div>\\n<script>(\\(function[\\s\\S]*?)<\\/script>/)[1];
global.window = global;
global.localStorage = {
  data: state.storage || {},
  getItem(k) { return k in this.data ? this.data[k] : null; },
  setItem(k, v) { this.data[k] = v; },
};
if (state.now) { Date.now = () => state.now; }
const timers = [];
global.setTimeout = (f, ms) => { timers.push({ f, ms }); return timers.length; };
global.clearTimeout = (id) => { if (timers[id - 1]) timers[id - 1].cleared = true; };
global.AbortController = class { constructor() { this.signal = {}; } abort() { this.aborted = true; } };
const fetchCalls = [];
if (state.fetch !== 'missing') {
  global.fetch = (url, options) => {
    fetchCalls.push({ url, options });
    if (state.fetch === 'hang') return new Promise(() => {});
    if (state.fetch === 'fail') return Promise.reject(new Error('network'));
    if (state.fetch === 'status') return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    if (state.fetch === 'malformed') return Promise.resolve({ ok: true, json: () => Promise.reject(new SyntaxError('x')) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve(state.answer) });
  };
}
const banner = { hidden: true, addEventListener() {}, querySelector: () => null };
global.document = { getElementById: () => banner, querySelectorAll: () => [] };
new Function(head)();
new Function(bannerScript)();
const snapshot = () => window.dataLayer.map((a) => Array.from(a));
const result = { commandsBefore: snapshot(), bannerShownBefore: banner.hidden === false };
(async () => {
  for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
  if (state.fetch === 'hang' && timers[0]) timers[0].f();
  result.commandsAfter = snapshot();
  result.bannerShownAfter = banner.hidden === false;
  result.fetchCalls = fetchCalls;
  result.timeouts = timers.map((t) => t.ms);
  result.storage = localStorage.data;
  result.needsNoticeSource = window.papyrusConsent.needsNotice ? window.papyrusConsent.needsNotice.toString() : null;
  console.log(JSON.stringify(result));
})();
"""


def render(**settings: object) -> str:
    chrome = SiteChrome(
        site_name="Anth.us", ga_measurement_id=MEASUREMENT_ID, consent_mode=ConsentModeSettings(**settings)
    )
    return render_page(
        title="Anth.us", fragment="<p>Home.</p>", active_href="index.html", nav_items=[NavItem("Home", "index.html")], chrome=chrome
    )


def visit(page: str, **state: object) -> dict:
    completed = subprocess.run(
        ["node", "-e", HARNESS, json.dumps(state)], input=page, capture_output=True, text=True, check=True
    )
    return json.loads(completed.stdout)


def consent_updates(commands: list) -> list:
    return [c[2] for c in commands if c[:2] == ["consent", "update"]]


def decide(answer: object) -> bool:
    """The page's own decision function, executed in node: True when the notice is needed."""
    source = visit(render(region_lookup=True), fetch="hang")["needsNoticeSource"]
    completed = subprocess.run(
        ["node", "-e", f"console.log(JSON.stringify(({source})(JSON.parse(process.argv[1]))))", json.dumps(answer)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(completed.stdout)


class RegionConstantTests(unittest.TestCase):
    def test_default_is_the_eea_plus_the_united_kingdom_and_switzerland(self) -> None:
        self.assertEqual(set(CONSENT_DENIED_BY_DEFAULT_REGIONS), EEA | {"GB", "CH"})
        self.assertEqual(len(CONSENT_DENIED_BY_DEFAULT_REGIONS), len(set(CONSENT_DENIED_BY_DEFAULT_REGIONS)))

    def test_the_list_is_marked_as_a_policy_choice_that_needs_review(self) -> None:
        source = (ROOT / "src/papyrus_content/markus_renderer/consent.py").read_text()
        before = source.split("CONSENT_DENIED_BY_DEFAULT_REGIONS: tuple")[0][-900:]
        self.assertIn("NOT LEGAL ADVICE", before)
        self.assertIn("must be reviewed", before)


class RegionLookupConfigurationTests(unittest.TestCase):
    def test_off_by_default_and_the_output_does_not_change(self) -> None:
        settings = ConsentModeSettings()
        self.assertFalse(settings.region_lookup)
        self.assertEqual(settings.region_lookup_address, "/_papyrus/consent")
        self.assertNotIn("fetch(", render())
        self.assertNotIn("needsNotice", render())

    def test_a_projection_mapping_turns_it_on(self) -> None:
        parsed = settings_from_mapping(
            {"chrome": {"ga_measurement_id": MEASUREMENT_ID, "consent_mode": {"region_lookup": True}}}
        )
        self.assertTrue(parsed.chrome.consent_mode.region_lookup)

    def test_regions_can_be_replaced_or_added_to(self) -> None:
        replaced = consent_mode_from_mapping({"denied_by_default_regions": ["DE"]})
        self.assertEqual(replaced.denied_by_default_regions, ("DE",))
        added = consent_mode_from_mapping({"additional_denied_by_default_regions": ["BR", "DE"]})
        self.assertEqual(added.denied_by_default_regions, CONSENT_DENIED_BY_DEFAULT_REGIONS + ("BR",))

    def test_invalid_values_raise_clear_errors(self) -> None:
        bad = [
            ({"region_lookup": "yes"}, "region_lookup must be true or false"),
            ({"region_lookup_address": "https://x.example/c"}, "site-absolute path"),
            ({"region_lookup_address": "//x.example/c"}, "site-absolute path"),
            ({"region_lookup_address": "/a b"}, "site-absolute path"),
            ({"region_lookup_timeout_milliseconds": 5}, "between 100 and 10000"),
            ({"region_lookup_timeout_milliseconds": True}, "between 100 and 10000"),
            ({"additional_denied_by_default_regions": "DE"}, "must be a list"),
            ({"additional_denied_by_default_regions": ["germany"]}, "ISO 3166"),
            ({"region_lookup": True, "additional_denied_by_default_regions": ["US-CA"]}, "two-letter country code"),
        ]
        for mapping, message in bad:
            with self.subTest(mapping=mapping), self.assertRaisesRegex(ValueError, message):
                consent_mode_from_mapping(mapping)

    def test_a_subdivision_is_fine_when_the_lookup_is_off(self) -> None:
        self.assertIn("US-CA", consent_mode_from_mapping({"additional_denied_by_default_regions": ["US-CA"]}).denied_by_default_regions)


@unittest.skipUnless(HAS_NODE, "node is required to execute the emitted consent scripts")
class RegionLookupBehaviourTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = render(region_lookup=True)

    def test_deny_is_the_default_before_the_answer_and_the_banner_waits(self) -> None:
        result = visit(self.page, fetch="hang")
        default = result["commandsBefore"][0]
        self.assertEqual(default[:2], ["consent", "default"])
        self.assertEqual(set(default[2][k] for k in ("ad_storage", "ad_user_data", "ad_personalization", "analytics_storage")), {"denied"})
        self.assertNotIn("region", default[2])
        self.assertEqual(result["commandsBefore"][-1][0], "config")  # nothing waited for the network
        self.assertFalse(result["bannerShownBefore"])

    def test_an_unregulated_visitor_gets_analytics_and_no_banner(self) -> None:
        result = visit(self.page, answer={"country": "US", "notice": False})
        self.assertEqual(consent_updates(result["commandsAfter"]), [{"analytics_storage": "granted"}])
        self.assertFalse(result["bannerShownAfter"])

    def test_a_regulated_visitor_sees_the_banner_and_stays_denied(self) -> None:
        result = visit(self.page, answer={"country": "DE", "notice": True})
        self.assertEqual(consent_updates(result["commandsAfter"]), [])
        self.assertTrue(result["bannerShownAfter"])

    def test_every_failure_shows_the_banner_and_stays_denied(self) -> None:
        cases = {
            "timeout": {"fetch": "hang"},
            "failed request": {"fetch": "fail"},
            "error status": {"fetch": "status"},
            "malformed body": {"fetch": "malformed"},
            "no fetch": {"fetch": "missing"},
            "unknown country": {"answer": {"country": "", "notice": False}},
            "string notice": {"answer": {"country": "US", "notice": "false"}},
            "no notice": {"answer": {"country": "US"}},
            "null answer": {"answer": None},
            "array answer": {"answer": [False]},
        }
        for label, state in cases.items():
            with self.subTest(label=label):
                result = visit(self.page, **state)
                self.assertTrue(result["bannerShownAfter"], label)
                self.assertEqual(consent_updates(result["commandsAfter"]), [], label)

    def test_the_decision_function(self) -> None:
        self.assertFalse(decide({"country": "US", "notice": False}))
        for answer in ({"country": "DE", "notice": True}, None, "x", [], {}, {"notice": False}, {"country": "us", "notice": False},
                       {"country": "USA", "notice": False}, {"country": "", "notice": False}):
            with self.subTest(answer=answer):
                self.assertTrue(decide(answer))

    def test_a_stored_choice_skips_the_lookup(self) -> None:
        now = 1_700_000_000_000
        stored = json.dumps({"version": 1, "savedAt": now, "granted": False})
        result = visit(self.page, storage={"anthus-consent": stored}, now=now + 1000, answer={"country": "US", "notice": False})
        self.assertEqual(result["fetchCalls"], [])
        self.assertFalse(result["bannerShownAfter"])
        self.assertEqual(consent_updates(result["commandsAfter"]), [{"ad_storage": "denied", "ad_user_data": "denied", "ad_personalization": "denied", "analytics_storage": "denied"}])

    def test_the_request_is_one_first_party_anonymous_call_with_a_short_timeout(self) -> None:
        result = visit(self.page, answer={"country": "US", "notice": False})
        self.assertEqual(len(result["fetchCalls"]), 1)
        call = result["fetchCalls"][0]
        self.assertEqual(call["url"], "/_papyrus/consent")
        self.assertEqual(call["options"]["credentials"], "omit")
        self.assertEqual(result["timeouts"], [1500])

    def test_the_country_is_never_stored_or_sent(self) -> None:
        result = visit(self.page, answer={"country": "US", "notice": False})
        self.assertNotIn("US", json.dumps(result["storage"]))
        self.assertNotIn("US", json.dumps(result["commandsAfter"]))
        lookup = self.page.split("c.needsNotice")[1].split("</script>")[0]
        self.assertNotIn("sendBeacon", lookup)
        self.assertNotIn("setItem", lookup)
        self.assertNotIn("gtag('set'", self.page.split("c.settle")[1].split("</script>")[0])

    def test_a_site_can_move_the_address_and_the_timeout(self) -> None:
        result = visit(render(region_lookup=True, region_lookup_address="/c/where", region_lookup_timeout_milliseconds=900), answer={"country": "US", "notice": False})
        self.assertEqual(result["fetchCalls"][0]["url"], "/c/where")
        self.assertEqual(result["timeouts"], [900])


class GuardedBuildTests(unittest.TestCase):
    def test_a_guarded_build_emits_no_analytics_and_no_lookup(self) -> None:
        import dataclasses

        chrome = SiteChrome(site_name="S", ga_measurement_id=MEASUREMENT_ID, consent_mode=ConsentModeSettings(region_lookup=True))
        guarded = dataclasses.replace(chrome, ga_measurement_id=None, ga_owner_opt_out=False, consent_mode=None)
        page = render_page(title="S", fragment="<p>x</p>", active_href="index.html", nav_items=[NavItem("Home", "index.html")], chrome=guarded)
        for fragment in ("gtag", "fetch(", "_papyrus/consent", "papyrus-consent"):
            self.assertNotIn(fragment, page)


class EdgeFunctionSourceTests(unittest.TestCase):
    def test_the_committed_function_list_is_generated_from_the_python_constant(self) -> None:
        sys.path.insert(0, str(ROOT / "infra" / "edge"))
        try:
            from generate_consent_region_function import FUNCTION_PATH, render_function
        finally:
            sys.path.pop(0)
        self.assertEqual(render_function(ConsentModeSettings()), FUNCTION_PATH.read_text())

    def test_a_site_override_flows_into_the_generated_list(self) -> None:
        sys.path.insert(0, str(ROOT / "infra" / "edge"))
        try:
            from generate_consent_region_function import render_function
        finally:
            sys.path.pop(0)
        text = render_function(ConsentModeSettings(denied_by_default_regions=("DE",), additional_denied_by_default_regions=("BR",)))
        self.assertIn('var NOTICE_COUNTRIES = ["DE","BR"];', text)


if __name__ == "__main__":
    unittest.main()
