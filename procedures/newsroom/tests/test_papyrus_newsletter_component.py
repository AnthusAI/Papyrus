"""The <papyrus-newsletter> form, run in Node against a fake DOM and a fake network."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest

from pathlib import Path

from papyrus_content.projection.plugins import PLUGIN_ASSET_DIRECTORY, plugin_static_files

COMPONENT = PLUGIN_ASSET_DIRECTORY / "papyrus-newsletter.js"

HARNESS = r"""
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; this.listeners = {}; this.style = {}; this.className = ""; this.value = ""; this.checked = false; this.disabled = false; this.textContent = ""; }
  get firstChild() { return this.children[0] || null; }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this.attributes[name] = String(value); if (name === "value") this.value = String(value); }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  dispatchEvent(event) { (this.events = this.events || []).push(event.detail); return true; }
  checkValidity() { return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(this.value); }
  find(predicate, found = []) { if (predicate(this)) found.push(this); this.children.forEach((child) => child.find(predicate, found)); return found; }
}
globalThis.HTMLElement = Node;
globalThis.CustomEvent = class { constructor(name, init) { this.name = name; this.detail = init.detail; } };
globalThis.document = { createElement: (tag) => new Node(tag) };
globalThis.window = { location: { origin: "https://news.example.com", pathname: "/roundup/" }, papyrusNewsletter: %(site)s };
let defined = null;
globalThis.customElements = { get: () => defined, define: (name, cls) => { defined = cls; } };
const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url, options, body: JSON.parse(options.body) });
  const reply = %(reply)s;
  return { status: reply.status, json: async () => { if (reply.broken) throw new Error("not json"); return reply.body; } };
};
const component = require(%(component)s);
function mount(attributes) {
  const element = new defined();
  element.attributes = Object.assign({}, attributes);
  element.connectedCallback();
  return element;
}
const byClass = (element, name) => element.find((node) => node.className === name);
(async () => {
  %(script)s
})().catch((error) => { console.error(error); process.exit(1); });
"""

ACCEPTED = {"status": 202, "body": {"status": "check_email"}}
LISTS = [{"id": "weekly", "name": "Weekly roundup", "description": "The week."}, {"id": "alerts-x", "name": "Alerts", "description": ""}]


def run_node(script: str, reply: dict | None = None, site: dict | None = None):
    code = HARNESS % {
        "component": json.dumps(str(COMPONENT)),
        "reply": json.dumps(reply or ACCEPTED),
        "site": json.dumps(site or {}),
        "script": script,
    }
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


SUBMIT = """
const el = mount(%s);
const input = byClass(el, "papyrus-newsletter-input")[0];
input.value = "reader@example.com";
%s
await byClass(el, "papyrus-newsletter")[0].listeners.submit({ preventDefault() {} });
await new Promise((resolve) => setTimeout(resolve, 10));
const status = byClass(el, "papyrus-newsletter-status")[0];
console.log(JSON.stringify({ calls: calls.map((call) => call.body), url: calls[0] && calls[0].url, options: calls[0] && calls[0].options, status: status.textContent, state: status.attributes["data-state"], events: el.events }));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class NewsletterComponentTests(unittest.TestCase):
    def test_one_list_has_no_checkbox_and_posts_the_consent_and_the_page(self) -> None:
        result = run_node(SUBMIT % (json.dumps({"lists": "weekly", "consent": "Send it.", "data-lists": json.dumps(LISTS)}), ""))
        self.assertEqual(result["url"], "/api/newsletter/subscribe")
        body = result["calls"][0]
        self.assertEqual(body["lists"], ["weekly"])
        self.assertEqual(body["email"], "reader@example.com")
        self.assertEqual(body["consent"], "Send it.")
        self.assertEqual(body["page"], "https://news.example.com/roundup/")
        self.assertEqual(body["website"], "")
        self.assertEqual(body["formId"], "newsletter")
        self.assertIsInstance(body["renderedAt"], int)
        self.assertEqual(result["options"]["credentials"], "same-origin")
        self.assertEqual(result["status"], "Check your inbox to confirm your subscription.")
        self.assertEqual(result["state"], "check_email")

    def test_several_lists_need_a_choice_and_post_the_chosen_ones(self) -> None:
        attributes = json.dumps({"lists": "weekly,alerts-x", "data-lists": json.dumps(LISTS)})
        none = run_node(SUBMIT % (attributes, ""))
        self.assertEqual(none["calls"], [])
        self.assertEqual(none["status"], "Error: choose at least one list.")
        chosen = run_node(SUBMIT % (attributes, 'byClass(el, "papyrus-newsletter-checkbox")[1].checked = true;'))
        self.assertEqual(chosen["calls"][0]["lists"], ["alerts-x"])

    def test_checkboxes_are_labelled_from_the_site_settings(self) -> None:
        script = (
            'const el = mount({ lists: "weekly,alerts-x" }); '
            'console.log(JSON.stringify(byClass(el, "papyrus-newsletter-list-label").map((node) => node.textContent)));'
        )
        labels = run_node(script, site={"lists": LISTS})
        self.assertEqual(labels, ["Weekly roundup: The week.", "Alerts"])

    def test_a_bad_address_is_refused_without_a_request(self) -> None:
        script = SUBMIT % (json.dumps({"lists": "weekly"}), 'input.value = "nope";')
        result = run_node(script)
        self.assertEqual(result["calls"], [])
        self.assertEqual(result["status"], "Error: please enter a valid email address.")

    def test_server_errors_become_words(self) -> None:
        attributes = json.dumps({"lists": "weekly"})
        invalid = run_node(SUBMIT % (attributes, ""), {"status": 400, "body": {"status": "invalid_email"}})
        self.assertEqual(invalid["status"], "Error: please enter a valid email address.")
        for reply in [{"status": 502, "body": {"error": "x"}}, {"status": 403, "body": {}}, {"status": 200, "broken": True}]:
            failed = run_node(SUBMIT % (attributes, ""), reply)
            self.assertTrue(failed["status"].startswith("Error: something went wrong"), failed)

    def test_a_form_without_lists_says_it_is_not_set_up(self) -> None:
        result = run_node(SUBMIT % ("{}", ""))
        self.assertEqual(result["calls"], [])
        self.assertEqual(result["status"], "Error: this form is not set up.")

    def test_the_honeypot_is_hidden_with_the_style_object_not_an_attribute(self) -> None:
        script = (
            'const el = mount({ lists: "weekly" }); const trap = byClass(el, "papyrus-newsletter-trap")[0];'
            "console.log(JSON.stringify({ attribute: trap.attributes.style || null, style: trap.style }));"
        )
        result = run_node(script)
        self.assertIsNone(result["attribute"])
        self.assertEqual(result["style"]["position"], "absolute")

    def test_the_source_stays_csp_safe(self) -> None:
        source = COMPONENT.read_text(encoding="utf-8")
        for forbidden in ["innerHTML", "outerHTML", "eval(", "new Function", "insertAdjacentHTML", 'setAttribute("style"', "document.write"]:
            self.assertNotIn(forbidden, source)


class NewsletterAssetTests(unittest.TestCase):
    def test_the_plugin_ships_its_component_under_a_versioned_name(self) -> None:
        files = plugin_static_files(["newsletter"])
        self.assertEqual(list(files), ["_plugins/papyrus-newsletter@1.js"])
        self.assertIn(b"papyrus-newsletter", files["_plugins/papyrus-newsletter@1.js"])

    def test_the_manifest_declares_exactly_what_the_projector_ships(self) -> None:
        source = (Path(__file__).resolve().parents[3] / "amplify" / "plugins" / "newsletter" / "papyrus.plugin.ts").read_text(encoding="utf-8")
        declared = re.search(r"staticAssets: \[(.*?)\]", source, re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', declared), list(plugin_static_files(["newsletter"])))
