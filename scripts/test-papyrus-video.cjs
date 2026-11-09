"use strict";
// Behaviour of the click-to-play video script (papyrus-video-v1.js) against a minimal DOM stub: no browser, no network.
// Run by features_backend/video-embed.feature ("the script swaps in the privacy-enhanced frame") and runnable alone: node scripts/test-papyrus-video.cjs
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const vm = require("node:vm");

const SCRIPT = readFileSync(
  resolve(__dirname, "..", "src/papyrus_content/projection/standard/assets/papyrus-video.js"),
  "utf8",
);
const NOCOOKIE = "https://www.youtube-nocookie.com/embed/";

class ClassList {
  constructor() { this.names = new Set(); }
  add(name) { this.names.add(name); }
  contains(name) { return this.names.has(name); }
}

class Element {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.attributes = {};
    this.children = [];
    this.listeners = {};
    this.classList = new ClassList();
    this.focused = false;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); return child; }
  get firstChild() { return this.children[0] || null; }
  addEventListener(type, handler) { (this.listeners[type] = this.listeners[type] || []).push(handler); }
  dispatch(type, event = {}) {
    const seen = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...event };
    for (const handler of this.listeners[type] || []) handler(seen);
    return seen;
  }
  focus() { this.focused = true; }
  querySelector(tag) {
    for (const child of this.children) {
      if (child.tagName === tag.toUpperCase()) return child;
      const deeper = child.querySelector(tag);
      if (deeper) return deeper;
    }
    return null;
  }
  frames() { return this.children.filter((child) => child.tagName === "IFRAME"); }
}

function player(embed, title = "Aircraft sound localisation demonstration") {
  const root = new Element("div");
  root.setAttribute("data-papyrus-video", "");
  root.setAttribute("data-embed", embed);
  root.setAttribute("data-title", title);
  root.appendChild(new Element("a"));
  root.appendChild(new Element("button"));
  return root;
}

function load(players) {
  const document = {
    readyState: "complete",
    createElement: (tag) => new Element(tag),
    querySelectorAll: () => players,
    addEventListener() {},
  };
  vm.runInNewContext(SCRIPT, { document });
  return document;
}

// Nothing is framed before a click, and the button is revealed.
const plain = player(`${NOCOOKIE}UytYrhYLOKI?autoplay=1&rel=0`);
const started = player(`${NOCOOKIE}UytYrhYLOKI?autoplay=1&start=90&rel=0`);
const keyboard = player(`${NOCOOKIE}UytYrhYLOKI?autoplay=1&rel=0`);
const space = player(`${NOCOOKIE}UytYrhYLOKI?autoplay=1&rel=0`);
const foreign = player("https://example.com/embed/UytYrhYLOKI?autoplay=1");
const all = [plain, started, keyboard, space, foreign];
load(all);
for (const each of all) {
  assert.equal(each.frames().length, 0, "no frame exists before a click");
  assert.ok(each.classList.contains("is-ready"), "the button is revealed once the script runs");
}

// A click swaps the poster for the privacy-enhanced frame, with the directive's title, and nothing else.
const held = plain.querySelector("button");
held.dispatch("click");
assert.equal(plain.frames().length, 1);
assert.equal(plain.children.length, 1, "the poster and link are replaced, not kept beside the frame");
const frame = plain.frames()[0];
assert.equal(frame.getAttribute("src"), `${NOCOOKIE}UytYrhYLOKI?autoplay=1&rel=0`);
assert.equal(frame.getAttribute("title"), "Aircraft sound localisation demonstration");
assert.equal(frame.getAttribute("loading"), "lazy");
assert.equal(frame.getAttribute("referrerpolicy"), "strict-origin-when-cross-origin");
assert.equal(frame.getAttribute("allow"), "autoplay; encrypted-media; picture-in-picture");
assert.equal(frame.getAttribute("allowfullscreen"), "");
assert.ok(frame.focused, "focus moves to the player");
assert.ok(plain.classList.contains("is-playing"));

// A second click does not add a second frame.
held.dispatch("click");
held.dispatch("keydown", { key: "Enter" });
assert.equal(plain.frames().length, 1, "a second activation does not add a second frame");
assert.equal(plain.querySelector("button"), null, "the button went with the poster");

// The start time the directive gave is in the address.
started.querySelector("button").dispatch("click");
assert.match(started.frames()[0].getAttribute("src"), /\?autoplay=1&start=90&rel=0$/);

// Enter plays and is not left to the browser (it would otherwise click a second time); a repeat does not duplicate.
const enter = keyboard.querySelector("button").dispatch("keydown", { key: "Enter" });
assert.ok(enter.defaultPrevented);
assert.equal(keyboard.frames().length, 1);
assert.equal(keyboard.frames().length, 1);

// Space plays too.
const spacebar = space.querySelector("button").dispatch("keydown", { key: " " });
assert.ok(spacebar.defaultPrevented);
assert.equal(space.frames().length, 1);

// Other keys do nothing.
const other = player(`${NOCOOKIE}UytYrhYLOKI?autoplay=1&rel=0`);
load([other]);
other.querySelector("button").dispatch("keydown", { key: "a" });
assert.equal(other.frames().length, 0);

// An address that is not the privacy-enhanced player is refused, however it got into the markup.
foreign.querySelector("button").dispatch("click");
assert.equal(foreign.frames().length, 0);

// Running the script again over a ready player does not attach a second handler.
const again = player(`${NOCOOKIE}UytYrhYLOKI?autoplay=1&rel=0`);
const document = load([again]);
vm.runInNewContext(SCRIPT, { document });
assert.equal(again.querySelector("button").listeners.click.length, 1);

// Each provider's own player address is accepted; a look-alike address on the same host is not.
for (const address of ["https://player.vimeo.com/video/76979871?autoplay=1&dnt=1", "https://www.instagram.com/p/C0abcDEfghI/embed/"]) {
  const other = player(address);
  load([other]);
  other.querySelector("button").dispatch("click");
  assert.equal(other.frames().length, 1, address);
}
for (const address of ["https://player.vimeo.com.evil.example/video/1", "https://www.instagram.com/accounts/login/", "https://vimeo.com/76979871"]) {
  const other = player(address);
  load([other]);
  other.querySelector("button").dispatch("click");
  assert.equal(other.frames().length, 0, address);
}

console.log("papyrus-video-v1.js: ok");
