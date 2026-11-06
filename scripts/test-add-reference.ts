import assert from "node:assert/strict";
import test from "node:test";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";
import { chromium } from "playwright";
import {
  addedMessage,
  addReference,
  normalizeAddStars,
  normalizeAddUrl,
  parseIntakeAnswer,
  type AddReferenceDeps,
} from "../lib/add-reference";

const root = new URL("..", import.meta.url).pathname;
const launch = () => chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });

function recorder(overrides: Partial<AddReferenceDeps> = {}) {
  const calls: string[] = [];
  const deps: AddReferenceDeps = {
    register: async (url) => { calls.push(`register ${url}`); return { id: "ref-1", curationStatus: "pending", reusedExisting: false }; },
    accept: async (id, note) => { calls.push(`accept ${id} ${note}`); },
    rate: async (id, stars) => { calls.push(`rate ${id} ${stars}`); },
    ...overrides,
  };
  return { calls, deps };
}

test("An address is registered first, then accepted, then rated, all on the same Reference", async () => {
  const { calls, deps } = recorder();
  const outcome = await addReference({ url: "https://example.org/a#frag", accept: true, stars: 5, note: " Really good. " }, deps);
  assert.deepEqual(calls, ["register https://example.org/a", "accept ref-1 Really good.", "rate ref-1 5"]);
  assert.deepEqual(outcome, { referenceId: "ref-1", alreadyThere: false, accepted: true, stars: 5, problems: [] });
  assert.equal(addedMessage(outcome), "Added to References. Accepted. Rated 5 of 5 stars.");
});

test("With no decision the Reference is only registered and stays pending", async () => {
  const { calls, deps } = recorder();
  const outcome = await addReference({ url: "https://example.org/a", accept: false, stars: null, note: "" }, deps);
  assert.deepEqual(calls, ["register https://example.org/a"]);
  assert.equal(addedMessage(outcome), "Added to References. It is pending review.");
});

test("A rating alone sends no separate accept, because the newsroom accepts a rated pending Reference itself", async () => {
  const { calls, deps } = recorder();
  await addReference({ url: "https://example.org/a", accept: false, stars: 3, note: "" }, deps);
  assert.deepEqual(calls, ["register https://example.org/a", "rate ref-1 3"]);
});

test("An address that is already a Reference is reported, and an already accepted one is not accepted twice", async () => {
  const { calls, deps } = recorder({ register: async () => ({ id: "ref-9", curationStatus: "accepted", reusedExisting: true }) });
  const outcome = await addReference({ url: "https://example.org/a", accept: true, stars: null, note: "" }, deps);
  assert.deepEqual(calls, []);
  assert.equal(outcome.alreadyThere, true);
  assert.equal(addedMessage(outcome), "This address was already a Reference. Accepted.");
});

test("Nothing is written for an address or rating that is not valid", async () => {
  const { calls, deps } = recorder();
  await assert.rejects(addReference({ url: "http://example.org/a", accept: false, stars: null, note: "" }, deps), /https address/);
  await assert.rejects(addReference({ url: "not a url", accept: false, stars: null, note: "" }, deps), /https address/);
  await assert.rejects(addReference({ url: "https://example.org/a", accept: false, stars: 6, note: "" }, deps), /1 to 5 stars/);
  await assert.rejects(addReference({ url: "https://example.org/a", accept: false, stars: 2.5, note: "" }, deps), /1 to 5 stars/);
  assert.deepEqual(calls, []);
  assert.equal(normalizeAddStars(null), null);
  assert.equal(normalizeAddUrl(" https://example.org/a?b=1#x "), "https://example.org/a?b=1");
});

test("A refused registration is an error, never a quiet success", async () => {
  const { deps } = recorder({ register: async () => { throw new Error("Intake is bound to this publication endpoint."); } });
  await assert.rejects(addReference({ url: "https://example.org/a", accept: true, stars: 4, note: "" }, deps), /bound to this publication/);
});

test("When the accept or the rating fails the Reference still exists, and the editor is told which step did not save", async () => {
  const { deps } = recorder({
    accept: async () => { throw new Error("Your session does not have permission."); },
    rate: async () => { throw new Error("busy"); },
  });
  const outcome = await addReference({ url: "https://example.org/a", accept: true, stars: 4, note: "" }, deps);
  assert.equal(outcome.referenceId, "ref-1");
  assert.equal(outcome.accepted, false);
  assert.equal(outcome.stars, null);
  assert.deepEqual(outcome.problems, [
    "It was added, but accepting it did not save: Your session does not have permission.",
    "It was added, but the 4-star rating did not save: busy",
  ]);
  assert.equal(addedMessage(outcome), "Added to References.");
});

test("The server's answer is read into the Reference it names, or its own refusal", () => {
  const ok = { ok: true, references: [{ id: "reference-x-v1", curationStatus: "pending" }] };
  assert.deepEqual(parseIntakeAnswer(JSON.stringify(ok)), { id: "reference-x-v1", curationStatus: "pending", reusedExisting: false });
  assert.equal(parseIntakeAnswer({ ok: true, references: [{ id: "a", reusedExisting: true }] }).reusedExisting, true);
  assert.throws(() => parseIntakeAnswer(JSON.stringify({ ok: false, errors: [{ code: "intake-rejected", message: "The corpus does not belong to this publication." }] })), /corpus does not belong/);
  assert.throws(() => parseIntakeAnswer(null), /did not accept/);
  assert.throws(() => parseIntakeAnswer("{"), /could not be read/);
  assert.throws(() => parseIntakeAnswer({ ok: true, references: [] }), /did not name/);
});

test("The dialog is buttons with marks and words, no drop-downs, no borders", async () => {
  (globalThis as { React?: typeof React }).React = React;
  const { ReferenceAddUrl } = await import("../components/reference-add-url");
  const html = renderToStaticMarkup(createElement(ReferenceAddUrl, { onAdd: async () => { throw new Error("unused"); } }));
  assert.ok(!/<select/i.test(html));
  assert.ok(!/\bborder\b|border-/.test(html), "flat tones only");
  assert.equal((html.match(/data-add-star="/g) ?? []).length, 5);
  assert.ok(html.includes(">Accept<") && html.includes("Not rated"), "state is written in words");
  assert.ok(html.includes('aria-pressed="false"'));
  assert.ok((html.match(/<svg/g) ?? []).length >= 6, "a check and five stars, as Lucide icons");
  assert.ok(html.includes("lucide-check") && html.includes("lucide-star"));
});

test("In the browser: accept and a star are chosen with buttons and are sent with the address", async () => {
  const bundled = await build({
    stdin: {
      contents: `import { createRoot } from "react-dom/client";
import { ReferenceAddUrl } from "./components/reference-add-url";
(window as any).sent = [];
createRoot(document.getElementById("root")!).render(
  <ReferenceAddUrl onAdd={async (input) => {
    (window as any).sent.push(input);
    if (input.url.includes("fail")) throw new Error("The newsroom did not accept this address.");
    return { referenceId: "r1", alreadyThere: false, accepted: input.accept, stars: input.stars, problems: [] };
  }} />);`,
      resolveDir: root, loader: "tsx", sourcefile: "entry.tsx",
    },
    bundle: true, write: false, platform: "browser", jsx: "automatic", define: { "process.env.NODE_ENV": '"development"' },
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' }, logLevel: "silent", absWorkingDir: root,
  });
  const browser = await launch();
  try {
    const page = await browser.newPage();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setContent('<div id="root"></div>');
    await page.addScriptTag({ content: bundled.outputFiles[0].text });

    const accept = page.getByRole("button", { name: "Accept" });
    assert.equal(await accept.getAttribute("aria-pressed"), "false");
    await accept.click();
    const accepted = page.getByRole("button", { name: "Accepted" });
    assert.equal(await accepted.getAttribute("aria-pressed"), "true");
    await page.getByLabel("Reason").fill("Primary source.");
    await page.getByRole("button", { name: "4 stars" }).click();
    assert.equal(await page.locator("[data-add-star-summary]").textContent(), "4 of 5 stars");
    assert.equal(await page.getByRole("button", { name: "4 stars" }).getAttribute("aria-pressed"), "true");
    await page.getByLabel("Reference URL").fill("https://example.org/a");
    await page.getByRole("button", { name: "Add reference" }).click();
    await page.getByText("Added to References. Accepted. Rated 4 of 5 stars.").waitFor();
    assert.deepEqual(await page.evaluate(() => (window as any).sent),
      [{ url: "https://example.org/a", accept: true, stars: 4, note: "Primary source." }]);
    assert.equal(await page.getByLabel("Reference URL").inputValue(), "", "the form is ready for the next address");
    assert.equal(await page.locator("[data-add-star-summary]").textContent(), "Not rated");

    // A press lights that star and every star to its left, by shape and by the written count; Accept follows the rating.
    await page.getByRole("button", { name: "3 stars" }).click();
    assert.deepEqual(await page.locator("[data-add-star] svg").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("fill"))),
      ["currentColor", "currentColor", "currentColor", "none", "none"]);
    assert.equal(await page.locator("[data-add-star-summary]").textContent(), "3 of 5 stars");
    assert.equal(await page.getByRole("button", { name: "Accepted" }).getAttribute("aria-pressed"), "true", "rating a reference also accepts it");
    await page.getByRole("button", { name: "2 stars" }).click();
    assert.equal(await page.locator("[data-add-star] [fill=currentColor]").count(), 2, "choosing a lower star empties those to its right");
    await page.getByRole("button", { name: "2 stars" }).click();
    assert.equal(await page.locator("[data-add-star-summary]").textContent(), "Not rated", "pressing the chosen star again clears it");

    await page.getByLabel("Reference URL").fill("https://example.org/fail");
    await page.getByRole("button", { name: "Add reference" }).click();
    await page.getByRole("alert").filter({ hasText: "Not added. The newsroom did not accept this address." }).waitFor();
    assert.equal(await page.getByLabel("Reference URL").inputValue(), "https://example.org/fail", "a failed add keeps what was typed");
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
