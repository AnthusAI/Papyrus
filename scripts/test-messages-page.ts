/** Fixture-only browser acceptance for the Messages page (every conversation) at 375 and 1440 pixels. No network beyond the fixture origin, no production reads. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://messages-page.test";
const shots = process.env.CONVERSATION_SHOTS_DIR;
let bundle: Promise<string> | undefined;
let tailwindCss: Promise<string> | undefined;

function compiledTailwind(): Promise<string> {
  tailwindCss ??= (async () => {
    const file = `${root}app/tailwind.css`;
    const { default: postcss } = await import("postcss");
    const { default: tailwind } = await import("@tailwindcss/postcss");
    return (await postcss([tailwind() as never]).process(fs.readFileSync(file, "utf8"), { from: file })).css;
  })();
  return tailwindCss;
}

function browserBundle(): Promise<string> {
  bundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic",
    define: { "process.env.NODE_ENV": '"development"' }, logLevel: "silent",
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' },
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "messages-page-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { ConversationsView } from "./components/conversations-view";
import { createMemoryConversationsSource } from "./components/conversations-memory-source";

const params = new URLSearchParams(location.search);
const NOW = Date.now();
const ago = (minutes) => new Date(NOW - minutes * 60000).toISOString();
const msg = (id, parent, author, content, minutes, sequenceNumber) => ({ id, parentMessageId: parent, authorLabel: author, content, createdAt: ago(minutes), sequenceNumber });
const by = (author) => JSON.stringify({ lastAuthorLabel: author });
const thread = (id, threadKind, title, minutes, extra = {}) => ({ id, threadKind, status: "active", title, messageCount: 1, createdAt: ago(minutes + 5), updatedAt: ago(minutes), lastMessageAt: ago(minutes), ...extra });
const reference = (id, title) => ({ id: id + "-v1", lineageId: id, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: id, title, sourceUri: "https://" + id + ".example.org/story", curationStatus: "pending", createdAt: ago(600), sourcePublishedAt: ago(600) });

const conversations = params.has("empty") ? [] : [
  { thread: thread("t-ref-1", "reference_conversation", "Water policy", 5, { primaryAnchorKind: "reference", primaryAnchorLineageId: "ref-1", primaryAnchorKey: "reference#ref-1", messageCount: 5, summary: "Drafting it Monday.", metadata: by("ada@example.test") }), messages: [
    msg("a1", null, "ada@example.test", "First thought on the water policy piece.", 90, 1),
    msg("a2", null, "grace@example.test", "The date range needs checking.", 80, 2),
    msg("a3", null, "ada@example.test", "Could anchor the Tuesday explainer.", 60, 3),
    msg("a4", null, "grace@example.test", "Agreed, and the numbers hold up.", 20, 4),
    msg("a5", "a4", "ada@example.test", "Drafting it Monday.", 5, 5),
  ] },
  { thread: thread("t-general", "conversation", "Council vote coverage", 30, { summary: "Should we cover the council vote?", metadata: by("grace@example.test") }), messages: [msg("g1", null, "ada@example.test", "Should we cover the council vote?", 30, 1)] },
  { thread: thread("t-story", "story_conversation", "Does the lede bury the vote", 45, { primaryAnchorKind: "item", primaryAnchorLineageId: "story-1", primaryAnchorKey: "item#story-1", summary: "The lede buries the vote.", metadata: by("grace@example.test") }), messages: [msg("s1", null, "grace@example.test", "The lede buries the vote.", 45, 1)] },
  { thread: thread("t-forum", "edition_forum", "Tuesday edition planning", 120, { messageCount: 7 }), messages: [] },
  { thread: thread("t-chat", "console", "Chat about the housing beat", 180, { messageCount: 12 }), messages: [] },
  { thread: thread("t-ref-2", "reference_conversation", "Transit funding", 240, { primaryAnchorKind: "reference", primaryAnchorLineageId: "ref-2", primaryAnchorKey: "reference#ref-2", summary: "Older note on transit.", metadata: by("ada@example.test") }), messages: [msg("b1", null, "ada@example.test", "Older note on transit.", 240, 1)] },
  { thread: thread("t-machine", "ingestion_rationale", "Why this Reference was kept", 1), messages: [msg("x1", null, "system", "A machine record.", 1, 1)] },
  ...(params.has("many") ? Array.from({ length: 14 }, (_, index) => ({ thread: thread("t-many-" + index, "conversation", "Extra conversation " + index, 300 + index, { summary: "Extra " + index }), messages: [msg("e" + index, null, "ada@example.test", "Extra " + index, 300 + index, 1)] })) : []),
];
const source = createMemoryConversationsSource("you@example.test", {
  conversations,
  references: {
    "ref-1": { reference: reference("ref-1", "Water policy shifts across three counties"), preview: { imageUrl: null, description: "What the new rules mean for farms and towns.", siteName: "Example Gazette", title: null } },
    "ref-2": { reference: reference("ref-2", "Transit funding fight reaches the state house"), preview: undefined },
  },
  stories: { "story-1": { title: "Council vote preview", stage: "Draft" } },
});
window.calls = [];
const post = source.post;
source.post = async (input) => {
  window.calls.push({ type: "post", threadId: input.thread.id, body: input.body, parentMessageId: input.parentMessageId });
  await new Promise((resolve) => setTimeout(resolve, 20));
  if (params.has("fail")) throw new Error("The backend refused this.");
  return post(input);
};
const start = source.start;
source.start = async (title, body) => { window.calls.push({ type: "start", title, body }); return start(title, body); };
const rename = source.rename;
source.rename = async (thread, title) => {
  window.calls.push({ type: "rename", threadId: thread.id, title });
  await new Promise((resolve) => setTimeout(resolve, 20));
  if (params.has("failrename")) throw new Error("The backend refused this.");
  return rename(thread, title);
};
const loadMessages = source.loadMessages;
source.loadMessages = async (threadId) => { window.calls.push({ type: "loadMessages", threadId }); return loadMessages(threadId); };

createRoot(document.getElementById("root")).render(<ConversationsView source={source} />);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const fixtureCss = "body{margin:0;font:16px sans-serif;background:#f4f1ea;color:#1c1c1c;--feed-card:#fbf9f4;--feed-control:#e8e3d8;--feed-footer:#f0ece2;--feed-radius-xl:12px;--feed-radius-lg:10px;--feed-radius-md:8px;--feed-radius-pill:8px;--feed-quiet:.6;--foreground-muted:#6b6b6b;--primary:#46560f;--primary-foreground:#fff}button,textarea{font:inherit}";

async function setup(options = "", width = 1440) {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  page.setDefaultTimeout(4000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    if (url.pathname.startsWith("/api/")) return route.abort();
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${tailwind}</style><style>${fixtureCss}</style></head><body><div id="root" class="p-4"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/${options}`);
  return { browser, page, errors };
}

async function run(options: string, widths: number[], body: (page: Page, width: number) => Promise<void>) {
  for (const width of widths) {
    const { browser, page, errors } = await setup(options, width);
    try {
      await body(page, width);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  }
}

const WIDE = [1024, 1440];
const NARROW = [375, 768, 834];
const cards = (page: Page) => page.locator("[data-conversation-card]");
const cardIds = (page: Page) => cards(page).evaluateAll((elements) => elements.map((element) => element.getAttribute("data-conversation-card")));
const calls = (page: Page) => page.evaluate(() => (window as unknown as { calls: unknown[] }).calls);
const section = (page: Page, key: string) => page.locator(`[data-conversation-section="${key}"]`);
async function open(page: Page, key: string) {
  await section(page, key).click();
  await page.waitForFunction((expected) => document.querySelector(`[data-conversation-section="${expected}"]`)?.getAttribute("aria-pressed") === "true", key);
  await page.waitForFunction(() => !document.querySelector("[data-conversations-loading]"));
}
async function screenshot(page: Page, name: string, width: number, selector?: string) {
  if (!shots) return;
  if (selector) await page.locator(selector).first().screenshot({ path: `${shots}/${name}-${width}.png` });
  else await page.screenshot({ path: `${shots}/${name}-${width}.png`, fullPage: true });
}

const pane = (page: Page) => page.locator("[data-list-detail-pane]");
const listColumn = (page: Page) => page.locator("[data-list-detail-list]");
const urlThread = (page: Page) => page.evaluate(() => new URLSearchParams(location.search).get("thread"));
async function openThread(page: Page, id: string) {
  await page.locator(`[data-conversation-card="${id}"]`).click();
  await page.locator(`[data-conversation-detail="${id}"] [data-conversation-thread]`).waitFor();
  await page.waitForFunction(() => !document.querySelector("[data-conversation-loading]"));
}

const scenarios: Record<string, () => Promise<void>> = {
  /** All is the default, in grid mode, with every conversation newest first and no machine records. */
  async all() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      assert.equal(await section(page, "all").getAttribute("aria-pressed"), "true", "All is the default");
      assert.deepEqual(await page.locator("[data-conversation-section]").evaluateAll((buttons) => buttons.map((button) => button.textContent?.trim())), ["All", "References", "Stories", "Chats", "Other"]);
      assert.deepEqual(await cardIds(page), ["t-ref-1", "t-general", "t-story", "t-forum", "t-chat", "t-ref-2"], "newest activity first, and no machine record");
      assert.equal(await page.locator("[data-conversation-new]").count(), 0, "no New thread form until it is asked for");
      assert.equal(await page.locator("[data-conversation-new-open]").count(), 1, "a New thread button");
      assert.equal(await page.locator("[data-conversations-view] select").count(), 0, "buttons, no drop-downs");
      assert.equal(await section(page, "references").locator("svg").count(), 1, "each section button has an icon");
      assert.equal(await page.locator('[data-conversation-layout="grid"]').getAttribute("aria-pressed"), "true", "grid by default");
      assert.equal(await page.locator("[data-conversation-grid]").count(), 1);
      assert.equal(await page.locator('[data-conversation-layout="grid"]').innerText(), "Grid");
      assert.equal(await page.locator('[data-conversation-layout="list"]').innerText(), "List");
      assert.equal(await page.locator("[data-conversation-layouts] svg").count(), 2, "an icon on each layout button");
      // A card is one thing: its own title, what it is attached to, the count, the last activity and a one-line preview.
      const card = page.locator('[data-conversation-card="t-ref-1"]');
      assert.equal(await card.locator("[data-conversation-title]").innerText(), "Water policy");
      await page.waitForFunction(() => document.querySelector('[data-conversation-card="t-ref-1"] [data-conversation-attached]'));
      const attached = await card.locator("[data-conversation-attached]").innerText();
      assert.ok(attached.includes("Example Gazette") && attached.includes("Water policy shifts across three counties"), "the site and the Reference's headline, as a small line");
      assert.equal((await card.locator("[data-conversation-count]").innerText()).trim(), "5");
      assert.equal(await card.locator("[data-conversation-count] svg").count(), 1, "a message icon beside the count");
      assert.equal(await card.locator("[data-conversation-activity]").innerText(), "ada · 5m ago");
      assert.equal(await card.locator("[data-conversation-preview]").innerText(), "Drafting it Monday.");
      assert.equal(await page.locator('[data-conversation-card="t-general"] [data-conversation-attached]').count(), 0, "nothing for an unattached conversation");
      // Nothing is read for a card, and a card holds no conversation.
      assert.equal(await page.locator("[data-conversation-card] [data-conversation-message], [data-conversation-card] [data-conversation-composer], [data-conversation-card] [data-conversation-show-all]").count(), 0, "no inline conversation");
      assert.deepEqual((await calls(page) as { type: string }[]).filter((entry) => entry.type === "loadMessages"), [], "no messages are read for the list");
      if (width >= 1024) {   // beside the list from 1024px; below it the detail takes the list's place
        await cards(page).first().locator("[data-conversation-open]").click();
        const chosen = page.locator("[data-conversation-card][data-selected]");
        await chosen.waitFor();
        assert.ok((await chosen.evaluate((element) => getComputedStyle(element).boxShadow)).includes("0px 0px 0px 4px"), "the open thread wears a ring around its outside");
        const unselected = await cards(page).nth(1).evaluate((element) => getComputedStyle(element).boxShadow);
        assert.ok(!unselected.includes("0px 0px 0px 4px"), "and only the open one");
      }
      await screenshot(page, "grid", width);
    });
  },

  /** The layout toggle: grid or list, remembered for this viewer. */
  async layout() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      await page.locator('[data-conversation-layout="list"]').click();
      assert.equal(await page.locator('[data-conversation-layout="list"]').getAttribute("aria-pressed"), "true");
      assert.equal(await page.locator('[data-conversation-layout="grid"]').getAttribute("aria-pressed"), "false");
      assert.equal(await page.locator("[data-conversation-lines]").count(), 1);
      const heights = await cards(page).evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
      assert.ok(heights.every((height) => height < 60), `each thread is one line: ${heights}`);
      const row = page.locator('[data-conversation-card="t-ref-1"]');
      assert.equal(await row.locator("[data-conversation-title]").innerText(), "Water policy");
      assert.equal((await row.locator("[data-conversation-count]").innerText()).trim(), "5");
      assert.equal(await row.locator("[data-conversation-preview]").count(), 0, "no preview on a line");
      await screenshot(page, "list", width);
      await page.reload();
      await cards(page).first().waitFor();
      await page.waitForFunction(() => document.querySelector('[data-conversation-layout="list"]')?.getAttribute("aria-pressed") === "true");
      assert.equal(await page.locator("[data-conversation-lines]").count(), 1, "remembered after a reload");
      await page.locator('[data-conversation-layout="grid"]').click();
      await page.reload();
      await cards(page).first().waitFor();
      assert.equal(await page.locator("[data-conversation-grid]").count(), 1, "and back to grid");
    });
    // Storage that refuses is not an error: the page still works.
    await run("", [1440], async (page) => {
      await page.addInitScript(() => { Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } }); });
      await page.reload();
      await cards(page).first().waitFor();
      await page.locator('[data-conversation-layout="list"]').click();
      assert.equal(await page.locator("[data-conversation-lines]").count(), 1);
    });
  },

  /** Each thread shows its own title, which can differ from the Reference's or Story's headline. */
  async titles() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      await page.waitForFunction(() => document.querySelector('[data-conversation-card="t-story"] [data-conversation-attached]'));
      const story = page.locator('[data-conversation-card="t-story"]');
      assert.equal(await story.locator("[data-conversation-title]").innerText(), "Does the lede bury the vote");
      const attached = await story.locator("[data-conversation-attached]").innerText();
      assert.ok(attached.includes("Council vote preview"), "the Story's own title is the small line");
      assert.ok((await story.locator("[data-conversation-stage]").innerText()).includes("Stage: Draft"), "its stage, as text");
      assert.equal(await page.locator('[data-conversation-card="t-ref-2"] [data-conversation-title]').innerText(), "Transit funding");
      await page.waitForFunction(() => document.querySelector('[data-conversation-card="t-ref-2"] [data-conversation-attached]'));
      assert.ok((await page.locator('[data-conversation-card="t-ref-2"] [data-conversation-attached]').innerText()).includes("Transit funding fight reaches the state house"));
    });
  },

  /** Each section shows only its own conversations; Chats and Other say what they hold; empty sections say so in plain words. */
  async sections() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      await open(page, "references");
      assert.deepEqual(await cardIds(page), ["t-ref-1", "t-ref-2"]);
      assert.equal(await page.locator("[data-conversation-new-open]").count(), 0, "no New thread button where a thread would not be unattached");
      await open(page, "stories");
      assert.deepEqual(await cardIds(page), ["t-story"]);
      await open(page, "chats");
      assert.deepEqual(await cardIds(page), ["t-chat"]);
      assert.ok((await page.locator('[data-conversation-card="t-chat"]').innerText()).toLowerCase().includes("open chat"));
      await open(page, "other");
      assert.deepEqual(await cardIds(page), ["t-general", "t-forum"], "unattached conversations and forum threads");
      assert.equal(await page.locator("[data-conversation-new-open]").count(), 1, "the New thread button is on Other");
      await open(page, "all");
      assert.equal((await cardIds(page)).length, 6);
    });
    await run("?empty=1", [375, 1440], async (page) => {
      await page.locator("[data-conversations-empty]").waitFor();
      assert.ok((await page.locator("[data-conversations-empty]").innerText()).includes("No conversations yet"));
      assert.equal(await page.locator("[data-conversations-empty] svg").count(), 1, "an icon beside the words");
      for (const [key, words] of [["references", "No Reference has a message yet"], ["stories", "No Story has a message yet"], ["chats", "No chats yet"], ["other", "No other conversations yet"]]) {
        await open(page, key);
        assert.ok((await page.locator("[data-conversations-empty]").innerText()).includes(words), key);
      }
    });
  },

  /** Selecting a thread opens its whole conversation: a pane beside the list from 1024px, in the list's place with Back below it. */
  async detail() {
    await run("", [...NARROW, ...WIDE], async (page, width) => {
      await cards(page).first().waitFor();
      await openThread(page, "t-ref-1");
      assert.equal(await urlThread(page), "t-ref-1", "the address holds the selection");
      const detail = page.locator('[data-conversation-detail="t-ref-1"]');
      assert.equal(await detail.locator("[data-conversation-detail-title]").innerText(), "Water policy", "the thread's own title");
      assert.equal(await detail.locator("[data-conversation-message]").count(), 5, "every message, not the latest few");
      assert.equal(await detail.locator("[data-conversation-replies] [data-conversation-message]").count(), 1, "the reply nested under its message");
      assert.equal(await detail.locator("[data-conversation-show-all]").count(), 0);
      assert.equal(await detail.locator('[data-conversation-composer="post"]').count(), 1, "Add a message…");
      assert.equal(await detail.locator("[data-conversation-reply]").count(), 5, "Reply on each message");
      const attachment = detail.locator("[data-conversation-attachment]");
      await attachment.waitFor();
      const text = await attachment.innerText();
      assert.ok(text.includes("Water policy shifts across three counties") && text.includes("What the new rules mean for farms and towns."), "the Reference's header");
      assert.equal(await attachment.getAttribute("href"), "/newsroom/references/ref-1");
      assert.equal(await detail.locator("[data-decision-control], [data-review-choice], [data-feed-actions]").count(), 0, "no decision controls");
      const loads = (await calls(page) as { type: string; threadId: string }[]).filter((entry) => entry.type === "loadMessages");
      assert.deepEqual(loads, [{ type: "loadMessages", threadId: "t-ref-1" }], "messages are read for the open thread only");
      const back = page.locator("[data-detail-back]");
      const paneBox = (await pane(page).boundingBox())!;
      if (WIDE.includes(width)) {
        assert.equal(await listColumn(page).isVisible(), true, "the list stays on the left");
        assert.equal(await back.isVisible(), false, "no Back control beside the list");
        const listBox = (await listColumn(page).boundingBox())!;
        assert.ok(paneBox.x >= listBox.x + listBox.width - 1, "the pane is to the right of the list");
        assert.ok(Math.abs(paneBox.width - (width >= 1280 ? 448 : 384)) < 2 || paneBox.width <= 448, `pane width ${paneBox.width}`);
        const lineWidth = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
        assert.equal(lineWidth, true, "nothing scrolls sideways");
        await screenshot(page, "detail", width);
        // Selecting another thread swaps the pane; closing is by selecting nothing (the address clears with Back below 1024px).
        await openThread(page, "t-general");
        assert.equal(await urlThread(page), "t-general");
        assert.equal(await page.locator("[data-conversation-detail]").count(), 1);
      } else {
        assert.equal(await listColumn(page).isVisible(), false, "the detail replaces the list");
        assert.ok(paneBox.width >= width - 40, `full width: ${paneBox.width}`);
        assert.equal(await back.isVisible(), true);
        assert.equal(await back.locator("svg").count(), 1, "an arrow beside the word");
        assert.ok((await back.innerText()).includes("Messages"));
        await screenshot(page, "detail", width);
        await back.click();
        assert.equal(await listColumn(page).isVisible(), true, "Back returns to the list");
        assert.equal(await pane(page).count(), 0);
        assert.equal(await urlThread(page), null, "and clears the address");
      }
    });
  },

  /** A linked address opens its thread, even one that is not on the first page; a thread that is not there says so. */
  async link() {
    await run("?thread=t-ref-2", [375, 1440], async (page, width) => {
      await page.locator('[data-conversation-detail="t-ref-2"] [data-conversation-thread]').waitFor();
      assert.equal(await page.locator("[data-conversation-detail-title]").innerText(), "Transit funding");
      assert.equal(await listColumn(page).isVisible(), width >= 1024);
    });
    await run("?many=1&thread=t-many-13", [1440], async (page) => {
      await page.locator('[data-conversation-detail="t-many-13"] [data-conversation-thread]').waitFor();
      assert.equal(await page.locator("[data-conversation-detail-title]").innerText(), "Extra conversation 13", "read by id, though it is on a later page");
    });
    await run("?thread=nope", [375], async (page) => {
      await page.locator("[data-conversations-notice]").waitFor();
      assert.ok((await page.locator("[data-conversations-notice]").innerText()).includes("could not be found"));
      assert.equal(await urlThread(page), null);
    });
  },

  /** A thread is renamed in its detail; a refused save says why in words and keeps the typed text. */
  async rename() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      await openThread(page, "t-general");
      const rename = page.locator("[data-conversation-rename]");
      assert.ok((await rename.innerText()).includes("Rename"));
      assert.equal(await rename.locator("svg").count(), 1, "a pencil beside the word");
      await rename.click();
      const input = page.locator("[data-conversation-rename-input]");
      assert.equal(await input.inputValue(), "Council vote coverage");
      await input.fill("Should we cover the council vote?");
      await screenshot(page, "rename", width);
      await page.locator("[data-conversation-rename-save]").click();
      await page.locator("[data-conversation-rename]").waitFor();
      assert.equal(await page.locator("[data-conversation-detail-title]").innerText(), "Should we cover the council vote?");
      assert.deepEqual((await calls(page) as { type: string }[]).filter((entry) => entry.type === "rename"), [{ type: "rename", threadId: "t-general", title: "Should we cover the council vote?" }]);
      if (width < 1024) await page.locator("[data-detail-back]").click();
      assert.equal(await page.locator('[data-conversation-card="t-general"] [data-conversation-title]').innerText(), "Should we cover the council vote?", "the list shows the new title");
      // Cancel leaves the title alone.
      await openThread(page, "t-general");
      await page.locator("[data-conversation-rename]").click();
      await page.locator("[data-conversation-rename-input]").fill("Not saved");
      await page.locator("[data-conversation-rename-cancel]").click();
      assert.equal(await page.locator("[data-conversation-detail-title]").innerText(), "Should we cover the council vote?");
    });
    await run("?failrename=1", [375], async (page) => {
      await cards(page).first().waitFor();
      await openThread(page, "t-general");
      await page.locator("[data-conversation-rename]").click();
      await page.locator("[data-conversation-rename-input]").fill("A better title");
      await page.locator("[data-conversation-rename-save]").click();
      const alert = page.locator("[data-conversation-rename-error]");
      await alert.waitFor();
      assert.equal(await alert.locator("svg").count(), 1, "an icon beside the words");
      assert.ok((await alert.innerText()).includes("The backend refused this."), "says why");
      assert.equal(await page.locator("[data-conversation-rename-input]").inputValue(), "A better title", "the text is kept");
    });
  },

  /** Replying in the detail nests under the message and is saved in that conversation with its parent. */
  async reply() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      await openThread(page, "t-general");
      const detail = page.locator('[data-conversation-detail="t-general"]');
      await detail.locator('[data-conversation-reply="g1"]').click();
      await detail.locator('[data-conversation-composer="reply"] textarea').fill("Yes, the vote is Thursday.");
      await detail.locator('[data-conversation-post="reply"]').click();
      await detail.locator("[data-conversation-replies] [data-conversation-message]").waitFor();
      await page.waitForFunction(() => !document.querySelector("[data-conversation-pending]"));
      assert.equal(await detail.locator("[data-conversation-replies] [data-conversation-content]").innerText(), "Yes, the vote is Thursday.");
      assert.deepEqual((await calls(page) as { type: string }[]).filter((entry) => entry.type === "post"), [{ type: "post", threadId: "t-general", body: "Yes, the vote is Thursday.", parentMessageId: "g1" }]);
      await detail.locator('[data-conversation-composer="post"] textarea').fill("And a top-level follow-up.");
      await detail.locator('[data-conversation-post="post"]').click();
      await page.waitForFunction(() => document.querySelectorAll('[data-conversation-detail="t-general"] [data-conversation-message]').length === 3);
      await page.waitForFunction(() => !document.querySelector("[data-conversation-pending]"));
      await screenshot(page, "reply", width);
      // The thread's card follows: one more message, newest first.
      if (width < 1024) await page.locator("[data-detail-back]").click();
      assert.equal((await page.locator('[data-conversation-card="t-general"] [data-conversation-count]').innerText()).trim(), "3");
      assert.equal((await cardIds(page))[0], "t-general", "the newest activity moves to the top");
      assert.equal(await page.locator('[data-conversation-card="t-general"] [data-conversation-preview]').innerText(), "And a top-level follow-up.");
    });
    // A refused save takes the message back, says so in words with an icon, and keeps the typed text.
    await run("?fail=1", [375], async (page) => {
      await cards(page).first().waitFor();
      await openThread(page, "t-general");
      const detail = page.locator('[data-conversation-detail="t-general"]');
      await detail.locator('[data-conversation-composer="post"] textarea').fill("Keep this text.");
      await detail.locator('[data-conversation-post="post"]').click();
      const alert = detail.locator("[data-conversation-error]");
      await alert.waitFor();
      assert.equal(await alert.locator("svg").count(), 1);
      assert.equal(await detail.locator('[data-conversation-composer="post"] textarea').inputValue(), "Keep this text.");
      assert.equal(await detail.locator("[data-conversation-message]").count(), 1);
    });
  },

  /** The New message box asks for a title and the first message, and starts a conversation about nothing but itself. */
  async start() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      assert.equal(await page.locator("[data-conversation-new]").count(), 0, "the form is not on the page until asked for");
      await page.locator("[data-conversation-new-open]").click();
      const box = page.locator("[data-conversation-new]");
      assert.ok(new URL(page.url()).searchParams.get("thread") === "new", "the New thread form is in the address");
      const post = box.locator('[data-conversation-post="post"]');
      await box.locator("textarea").fill("A loose thought about the budget.");
      assert.equal(await post.isDisabled(), true, "a title is required");
      assert.ok((await box.locator("[data-conversation-blocked]").innerText()).includes("Add a title"), "said in words");
      await box.locator("[data-conversation-new-title]").fill("Budget thoughts");
      assert.equal(await post.isDisabled(), false);
      await screenshot(page, "new", width);
      await post.click();
      await page.waitForFunction(() => document.querySelector("[data-conversation-card]")?.getAttribute("data-conversation-card")?.startsWith("message-thread-conversation-new-"));
      const first = cards(page).first();
      assert.equal(await first.getAttribute("data-conversation-kind"), "conversation");
      assert.equal(await first.locator("[data-conversation-title]").innerText(), "Budget thoughts", "the title is the thread's own");
      assert.equal(await first.locator("[data-conversation-preview]").innerText(), "A loose thought about the budget.");
      assert.equal(await first.locator("[data-conversation-attached]").count(), 0, "attached to nothing");
      assert.deepEqual((await calls(page) as { type: string }[]).filter((entry) => entry.type === "start"), [{ type: "start", title: "Budget thoughts", body: "A loose thought about the budget." }]);
      assert.equal(await page.locator("[data-conversation-new]").count(), 0, "the form gives way to the new thread");
      assert.ok((await page.locator("[data-conversation-detail]").getAttribute("data-conversation-detail"))?.startsWith("message-thread-conversation-new-"), "the new thread is open in the detail view");
      if (width < 1024) await page.locator("[data-detail-back]").click();   // on a phone the thread took the list's place
      await open(page, "other");
      assert.equal((await cardIds(page))[0]?.startsWith("message-thread-conversation-new-"), true, "and it is under Other");
    });
  },

  /** Forum threads and chats are cards too; they open their own views. */
  async forum() {
    await run("", [375, 1440], async (page) => {
      await open(page, "other");
      const card = page.locator('[data-conversation-card="t-forum"]');
      assert.ok((await card.innerText()).includes("Tuesday edition planning"));
      assert.equal((await card.locator("[data-conversation-count]").innerText()).trim(), "7");
      const open_ = card.locator("[data-conversation-open]");
      assert.equal(await open_.getAttribute("href"), "/newsroom/forum/t-forum");
      assert.ok((await card.innerText()).toLowerCase().includes("open thread"));
      assert.equal(await card.locator("[data-conversation-composer]").count(), 0, "answered in its own thread view");
      await card.click();
      assert.equal(await pane(page).count(), 0, "it does not open a pane here");
      await open(page, "chats");
      assert.equal(await page.locator('[data-conversation-card="t-chat"] button[data-conversation-open]').count(), 1, "a chat opens in the console");
    });
  },

  /** More conversations are read only when asked for, in order. */
  async paging() {
    await run("?many=1", [1440], async (page) => {
      await cards(page).first().waitFor();
      assert.equal((await cardIds(page)).length, 12, "one page");
      await page.locator("[data-conversations-more]").click();
      await page.waitForFunction(() => document.querySelectorAll("[data-conversation-card]").length === 20);
      assert.equal(await page.locator("[data-conversations-more]").count(), 0, "nothing more to ask for");
      const ids = await cardIds(page);
      assert.equal(new Set(ids).size, ids.length, "no conversation twice");
      assert.equal(ids.at(-1), "t-many-13", "oldest last");
    });
  },

  /** Flat tones and rounded rectangles: no borders, outlines or rules anywhere on the page, in either layout, with the detail open. */
  async design() {
    for (const layoutMode of ["grid", "list"]) {
      await run("", [375, 1024, 1440], async (page, width) => {
        await cards(page).first().waitFor();
        if (layoutMode === "list") await page.locator('[data-conversation-layout="list"]').click();
        await openThread(page, "t-ref-1");
        await page.locator('[data-conversation-detail="t-ref-1"] [data-conversation-reply="a1"]').click();
        await page.locator('[data-conversation-detail="t-ref-1"] [data-conversation-rename]').click();
        const offenders = await page.locator("[data-conversations-view], [data-conversations-view] *").evaluateAll((elements) => elements.flatMap((element) => {
          const style = getComputedStyle(element);
          const edges = ["top", "right", "bottom", "left"].some((edge) => parseFloat(style.getPropertyValue(`border-${edge}-width`)) > 0 && style.getPropertyValue(`border-${edge}-style`) !== "none");
          const outline = parseFloat(style.outlineWidth) > 0 && style.outlineStyle !== "none";
          return edges || outline ? [element.tagName.toLowerCase() + "." + String(element.getAttribute("class")).slice(0, 40)] : [];
        }));
        assert.deepEqual(offenders, [], `${layoutMode} ${width}: no borders or outlines`);
        const radius = await pane(page).evaluate((element) => parseFloat(getComputedStyle(element).borderTopLeftRadius));
        assert.ok(radius >= 8, "rounded rectangles");
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
        if (width >= 1024 && layoutMode === "list") {
          const heights = await cards(page).evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
          assert.ok(heights.every((height) => height < 60), `lines stay one line beside the pane: ${heights}`);
        }
      });
    }
  },
};

async function main() {
  const requested = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested && requested !== name) continue;
    await scenario();
    console.log(`Messages page scenario passed: ${name}`);
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
