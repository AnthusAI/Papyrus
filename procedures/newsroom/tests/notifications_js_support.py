"""Runs the notifications plugin's browser scripts in Node against a small fake DOM and a fake network (no browser, no AWS).

The pages script runs against the real projected markup: ``run_page`` parses the page the standard projector wrote, so a change to the
markup that the script depends on fails here. The web component runs against the same fake DOM.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from papyrus_content.projection.plugins import PLUGIN_ASSET_DIRECTORY

PAGES_SCRIPT = PLUGIN_ASSET_DIRECTORY / "papyrus-notifications-pages.js"
COMPONENT_SCRIPT = PLUGIN_ASSET_DIRECTORY / "papyrus-notifications.js"
HAS_NODE = shutil.which("node") is not None

DOM = r"""
const VOID = new Set(["input", "br", "img", "meta", "link", "hr"]);
class El {
  constructor(tag, attrs) {
    this.tag = tag; this.attrs = attrs || {}; this.children = []; this.parent = null; this.listeners = {}; this.events = [];
    this._text = null; this.style = {}; this.disabled = false; this.innerHTML = "";
    this.className = this.attrs.class || ""; this.value = this.attrs.value || ""; this.name = this.attrs.name || ""; this.type = this.attrs.type || "";
    this.id = this.attrs.id || ""; this.href = this.attrs.href || ""; this.checked = false;
  }
  get hidden() { return "hidden" in this.attrs; }
  set hidden(on) { if (on) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get firstChild() { return this.children[0] || null; }
  get textContent() { if (this.tag === "#text" || this._text !== null) return this._text; return this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this.children = []; this._text = String(value); }
  get elements() { const found = {}; this.walk((node) => { if (node.tag === "input" && node.name) found[node.name] = node; }); return found; }
  appendChild(child) { this._text = null; child.parent = this; this.children.push(child); return child; }
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
  setAttribute(name, value) { this.attrs[name] = String(value); if (name === "class") this.className = String(value); if (name === "type") this.type = String(value); if (name === "name") this.name = String(value); }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  dispatchEvent(event) { this.events.push(event.detail); return true; }
  checkValidity() { return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(this.value); }
  click() { if (this.listeners.click) this.listeners.click({}); }
  walk(visit) { this.children.forEach((child) => { visit(child); child.walk(visit); }); }
  matchesCompound(compound) {
    const m = /^([a-z0-9-]*)((?:\[[^\]]+\])*)((?:\.[\w-]+)*)$/.exec(compound);
    if (!m) throw new Error("unsupported selector " + compound);
    if (m[1] && m[1] !== this.tag) return false;
    for (const [, name, value] of (m[2].match(/\[[^\]]+\]/g) || []).map((part) => /^\[([\w-]+)(?:=([^\]]*))?\]$/.exec(part))) {
      if (!(name in this.attrs)) return false;
      if (value !== undefined && this.attrs[name] !== value) return false;
    }
    return (m[3].match(/\.[\w-]+/g) || []).every((cls) => this.className.split(/\s+/).includes(cls.slice(1)));
  }
  queryAll(selector) {
    const parts = selector.trim().split(/\s+/);
    const found = [];
    this.walk((node) => {
      if (!node.matchesCompound(parts[parts.length - 1])) return;
      let at = node.parent; let index = parts.length - 2;
      while (index >= 0 && at) { if (at.tag !== "#root" && at.matchesCompound(parts[index])) index -= 1; at = at.parent; }
      if (index < 0) found.push(node);
    });
    return found;
  }
  querySelector(selector) { return this.queryAll(selector)[0] || null; }
  querySelectorAll(selector) { return this.queryAll(selector); }
}
function parse(html) {
  const root = new El("#root"); let at = root;
  for (const token of html.match(/<[^>]+>|[^<]+/g) || []) {
    if (token.startsWith("</")) { at = at.parent || root; continue; }
    if (token.startsWith("<")) {
      const m = /^<([a-zA-Z0-9-]+)((?:\s+[^\s=>\/]+(?:="[^"]*")?)*)\s*\/?>$/.exec(token);
      if (!m) throw new Error("cannot parse " + token);
      const attrs = {}; for (const a of m[2].matchAll(/([^\s=]+)(?:="([^"]*)")?/g)) attrs[a[1]] = a[2] === undefined ? "" : a[2].replace(/&amp;/g, "&");
      const node = new El(m[1], attrs); at.appendChild(node);
      if (!VOID.has(m[1]) && !token.endsWith("/>")) at = node;
    } else { const text = new El("#text"); text._text = token.replace(/&amp;/g, "&").replace(/&#x27;/g, "'"); at.appendChild(text); }
  }
  return root;
}
const requests = [];
function installNetwork(replies) {
  globalThis.fetch = async (url, options) => {
    requests.push({ url, method: (options && options.method) || "GET", body: options && options.body ? JSON.parse(options.body) : null });
    const key = Object.keys(replies).find((prefix) => url.startsWith(prefix));
    const reply = key ? replies[key] : { status: 503, body: { status: "unavailable" } };
    if (reply.reject) throw new Error("network down");
    return { ok: reply.status >= 200 && reply.status < 300, status: reply.status, json: async () => { if (reply.broken) throw new Error("not json"); return reply.body; } };
  };
}
const tracked = [];
globalThis.CustomEvent = class { constructor(name, init) { this.name = name; this.detail = init.detail; } };
let defined = null;
globalThis.customElements = { get: () => defined, define: (name, cls) => { defined = cls; } };
const settle = () => new Promise((resolve) => setTimeout(resolve, 20));
"""

PAGE_HARNESS = DOM + r"""
globalThis.HTMLElement = El;
const html = %(html)s;
const tree = parse(html);
let replaced = null;
globalThis.document = { readyState: "complete", querySelector: (selector) => tree.querySelector(selector), createElement: (tag) => new El(tag), createTextNode: (text) => { const n = new El("#text"); n._text = text; return n; }, addEventListener() {} };
globalThis.window = { location: { search: %(search)s, replace: (href) => { replaced = href; } }, sessionStorage: { getItem: () => null, setItem() {} }, papyrusAnalytics: { track: (...args) => tracked.push(args) } };
installNetwork(%(replies)s);
const $ = (selector) => tree.querySelector(selector);
const visible = (selector) => { const node = $(selector); return node !== null && !node.hidden; };
const text = (selector) => ($(selector) || { textContent: null }).textContent;
require(%(script)s);
(async () => {
  await settle();
  %(body)s
})().catch((error) => { console.error(error); process.exit(1); });
"""

COMPONENT_HARNESS = DOM + r"""
globalThis.HTMLElement = El;
globalThis.document = { createElement: (tag) => new El(tag) };
globalThis.window = { location: { origin: "https://news.example.com", pathname: "/notifications/" } };
installNetwork(%(replies)s);
require(%(script)s);
const byClass = (node, name) => node.queryAll("." + name);
function mount(attributes) { const node = new defined(); node.attrs = Object.assign({}, attributes); node.connectedCallback(); return node; }
(async () => {
  await settle();
  %(body)s
})().catch((error) => { console.error(error); process.exit(1); });
"""


def main_html(page_html: str) -> str:
    """The content of ``<main>``: the page's own markup, without the site chrome."""
    return page_html.split('<main id="main">', 1)[1].split("</main>", 1)[0]


def _run(code: str):
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise AssertionError(done.stderr or done.stdout)
    return json.loads(done.stdout.strip().splitlines()[-1])


def run_page(page_html: str, search: str, replies: dict, body: str):
    """Run the pages script on one projected page. ``body`` is JavaScript with ``$``, ``visible``, ``text``, ``replaced``, ``requests`` and ``tracked`` in scope and prints one JSON line."""
    code = PAGE_HARNESS % {
        "html": json.dumps(main_html(page_html)),
        "search": json.dumps(search),
        "replies": json.dumps(replies),
        "script": json.dumps(str(PAGES_SCRIPT)),
        "body": body,
    }
    return _run(code)


def run_component(replies: dict, body: str):
    """Run the web component. ``body`` has ``mount``, ``byClass``, ``requests`` and ``settle`` in scope and prints one JSON line."""
    code = COMPONENT_HARNESS % {"replies": json.dumps(replies), "script": json.dumps(str(COMPONENT_SCRIPT)), "body": body}
    return _run(code)


CONSENT = "I agree to get the emails I choose from Example News and can unsubscribe at any time."
OFFERED_ONE = {"status": 200, "body": {"status": "ready", "consent": CONSENT, "lists": [{"id": "stories", "name": "New stories", "description": ""}]}}
OFFERED_TWO = {
    "status": 200,
    "body": {
        "status": "ready",
        "consent": CONSENT,
        "lists": [
            {"id": "stories", "name": "New stories", "description": "Each new story as it is published."},
            {"id": "weekly", "name": "Weekly roundup", "description": ""},
        ],
    },
}
