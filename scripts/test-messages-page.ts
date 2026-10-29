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
const thread = (id, threadKind, title, minutes, extra = {}) => ({ id, threadKind, status: "active", title, messageCount: 1, createdAt: ago(minutes + 5), updatedAt: ago(minutes), lastMessageAt: ago(minutes), ...extra });
const reference = (id, title) => ({ id: id + "-v1", lineageId: id, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: id, title, sourceUri: "https://" + id + ".example.org/story", curationStatus: "pending", createdAt: ago(600), sourcePublishedAt: ago(600) });

const conversations = params.has("empty") ? [] : [
  { thread: thread("t-ref-1", "reference_conversation", "Water policy", 5, { primaryAnchorKind: "reference", primaryAnchorLineageId: "ref-1", primaryAnchorKey: "reference#ref-1", messageCount: 5 }), messages: [
    msg("a1", null, "ada@example.test", "First thought on the water policy piece.", 90, 1),
    msg("a2", null, "grace@example.test", "The date range needs checking.", 80, 2),
    msg("a3", null, "ada@example.test", "Could anchor the Tuesday explainer.", 60, 3),
    msg("a4", null, "grace@example.test", "Agreed, and the numbers hold up.", 20, 4),
    msg("a5", "a4", "ada@example.test", "Drafting it Monday.", 5, 5),
  ] },
  { thread: thread("t-general", "conversation", "Should we cover the council vote", 30), messages: [msg("g1", null, "ada@example.test", "Should we cover the council vote?", 30, 1)] },
  { thread: thread("t-story", "story_conversation", "Council vote preview", 45, { primaryAnchorKind: "item", primaryAnchorLineageId: "story-1", primaryAnchorKey: "item#story-1" }), messages: [msg("s1", null, "grace@example.test", "The lede buries the vote.", 45, 1)] },
  { thread: thread("t-forum", "edition_forum", "Tuesday edition planning", 120, { messageCount: 7 }), messages: [] },
  { thread: thread("t-chat", "console", "Chat about the housing beat", 180, { messageCount: 12 }), messages: [] },
  { thread: thread("t-ref-2", "reference_conversation", "Transit funding", 240, { primaryAnchorKind: "reference", primaryAnchorLineageId: "ref-2", primaryAnchorKey: "reference#ref-2" }), messages: [msg("b1", null, "ada@example.test", "Older note on transit.", 240, 1)] },
  { thread: thread("t-machine", "ingestion_rationale", "Why this Reference was kept", 1), messages: [msg("x1", null, "system", "A machine record.", 1, 1)] },
  ...(params.has("many") ? Array.from({ length: 14 }, (_, index) => ({ thread: thread("t-many-" + index, "conversation", "Extra conversation " + index, 300 + index), messages: [msg("e" + index, null, "ada@example.test", "Extra " + index, 300 + index, 1)] })) : []),
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
source.start = async (body) => { window.calls.push({ type: "start", body }); return start(body); };

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

const scenarios: Record<string, () => Promise<void>> = {
  /** All is the default and lists every conversation, newest activity first, with no machine records. */
  async all() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      assert.equal(await section(page, "all").getAttribute("aria-pressed"), "true", "All is the default");
      assert.deepEqual(await page.locator("[data-conversation-section]").evaluateAll((buttons) => buttons.map((button) => button.textContent?.trim())), ["All", "References", "Stories", "Chats", "Other"]);
      assert.deepEqual(await cardIds(page), ["t-ref-1", "t-general", "t-story", "t-forum", "t-chat", "t-ref-2"], "newest activity first, and no machine record");
      assert.equal(await page.locator("[data-conversation-new]").count(), 1, "a New message box at the top");
      assert.equal(await page.locator("[data-conversations-view] select").count(), 0, "buttons, no drop-downs");
      assert.equal(await section(page, "references").locator("svg").count(), 1, "each section button has an icon");
      assert.equal(await page.locator('[data-conversation-card="t-ref-1"] [data-conversation-activity]').innerText(), "Active 5m ago");
      await screenshot(page, "all", width);
    });
  },

  /** Each section shows only its own conversations; Chats and Other say what they hold; empty sections say so in plain words. */
  async sections() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      await open(page, "references");
      assert.deepEqual(await cardIds(page), ["t-ref-1", "t-ref-2"]);
      assert.equal(await page.locator("[data-conversation-new]").count(), 0, "no New message box where a message would not be unattached");
      await open(page, "stories");
      assert.deepEqual(await cardIds(page), ["t-story"]);
      const story = page.locator("[data-conversation-story]");
      assert.ok((await story.innerText()).includes("Council vote preview"), "the Story's title");
      assert.ok((await page.locator("[data-conversation-stage]").innerText()).includes("Stage: Draft"), "its stage, as text");
      assert.equal(await story.locator("a").getAttribute("href"), "/newsroom/articles/story-1");
      await open(page, "chats");
      assert.deepEqual(await cardIds(page), ["t-chat"]);
      assert.ok((await page.locator("[data-conversation-open]").innerText()).includes("Open chat"));
      await open(page, "other");
      assert.deepEqual(await cardIds(page), ["t-general", "t-forum"], "unattached conversations and forum threads");
      assert.equal(await page.locator("[data-conversation-new]").count(), 1, "the New message box is on Other");
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

  /** A Reference conversation leads with its messages, then the Reference as an attachment with no decision controls. */
  async reference() {
    await run("", [375, 1440], async (page, width) => {
      const card = page.locator('[data-conversation-card="t-ref-1"]');
      await card.waitFor();
      await card.locator("[data-conversation-attachment]").waitFor();
      const messagesFirst = await card.evaluate((element) => {
        const message = element.querySelector("[data-conversation-message]")!;
        const attachment = element.querySelector("[data-conversation-attachment]")!;
        return Boolean(message.compareDocumentPosition(attachment) & Node.DOCUMENT_POSITION_FOLLOWING);
      });
      assert.equal(messagesFirst, true, "the messages come first, the Reference below");
      const attachment = card.locator("[data-conversation-attachment]");
      const text = await attachment.innerText();
      assert.ok(text.includes("Water policy shifts across three counties"), "the headline");
      assert.ok(text.includes("What the new rules mean for farms and towns."), "the dek");
      assert.equal(await attachment.locator("[data-feed-image]").count(), 1, "the picture frame");
      assert.equal(await attachment.getAttribute("href"), "/newsroom/references/ref-1", "it opens the Reference");
      assert.equal(await card.locator("[data-decision-control], [data-review-choice], [data-feed-actions]").count(), 0, "no decision controls");
      // Latest messages first, the rest one button away.
      assert.equal(await card.locator("[data-conversation-message]").count(), 4, "the newest three messages and the reply to the last");
      const showAll = card.locator("[data-conversation-show-all]");
      assert.ok((await showAll.innerText()).includes("Show all 5 messages"));
      assert.equal(await showAll.locator("svg").count(), 1);
      await showAll.click();
      assert.equal(await card.locator("[data-conversation-message]").count(), 5);
      assert.equal(await card.locator("[data-conversation-show-all]").count(), 0);
      // Without a stored picture the attachment still reads as a Reference.
      assert.ok((await page.locator('[data-conversation-card="t-ref-2"] [data-conversation-attachment]').innerText()).includes("Transit funding fight"));
      await screenshot(page, "reference-card", width, '[data-conversation-card="t-ref-1"]');
    });
  },

  /** Replying on the Messages page nests under the message and is saved against that conversation. */
  async reply() {
    await run("", [375, 1440], async (page, width) => {
      const card = page.locator('[data-conversation-card="t-general"]');
      await card.waitFor();
      await card.locator('[data-conversation-reply="g1"]').click();
      await card.locator('[data-conversation-composer="reply"] textarea').fill("Yes, the vote is Thursday.");
      await card.locator('[data-conversation-post="reply"]').click();
      await card.locator("[data-conversation-replies] [data-conversation-message]").waitFor();
      await page.waitForFunction(() => !document.querySelector("[data-conversation-pending]"));
      assert.equal(await card.locator("[data-conversation-replies] [data-conversation-content]").innerText(), "Yes, the vote is Thursday.");
      assert.deepEqual(await calls(page), [{ type: "post", threadId: "t-general", body: "Yes, the vote is Thursday.", parentMessageId: "g1" }]);
      await card.locator('[data-conversation-composer="post"] textarea').fill("And a top-level follow-up.");
      await card.locator('[data-conversation-post="post"]').click();
      await page.waitForFunction(() => document.querySelectorAll('[data-conversation-card="t-general"] [data-conversation-message]').length === 3);
      await screenshot(page, "reply-on-page", width, '[data-conversation-card="t-general"]');
    });
    // A refused save takes the message back, says so in words with an icon, and keeps the typed text.
    await run("?fail=1", [375], async (page) => {
      const card = page.locator('[data-conversation-card="t-general"]');
      await card.locator('[data-conversation-composer="post"] textarea').fill("Keep this text.");
      await card.locator('[data-conversation-post="post"]').click();
      const alert = card.locator("[data-conversation-error]");
      await alert.waitFor();
      assert.equal(await alert.locator("svg").count(), 1);
      assert.equal(await card.locator('[data-conversation-composer="post"] textarea').inputValue(), "Keep this text.");
      assert.equal(await card.locator("[data-conversation-message]").count(), 1);
    });
  },

  /** The New message box starts a conversation about nothing but itself, and it appears first. */
  async start() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      const box = page.locator('[data-conversation-new] [data-conversation-composer="post"]');
      await box.locator("textarea").fill("A loose thought about the budget.");
      await box.locator('[data-conversation-post="post"]').click();
      await page.waitForFunction(() => document.querySelector("[data-conversation-card]")?.getAttribute("data-conversation-card")?.startsWith("message-thread-conversation-new-"));
      const first = cards(page).first();
      assert.equal(await first.getAttribute("data-conversation-kind"), "conversation");
      assert.ok((await first.innerText()).includes("A loose thought about the budget."));
      assert.equal(await first.locator("[data-conversation-attachment], [data-conversation-story]").count(), 0, "attached to nothing");
      assert.deepEqual(await calls(page), [{ type: "start", body: "A loose thought about the budget." }]);
      assert.equal(await box.locator("textarea").inputValue(), "", "the box clears");
      await open(page, "other");
      assert.equal((await cardIds(page))[0]?.startsWith("message-thread-conversation-new-"), true, "and it is under Other");
      await screenshot(page, "other", width);
    });
  },

  /** Forum threads are ordinary conversations under Other, and open their own thread view. */
  async forum() {
    await run("", [375, 1440], async (page) => {
      await open(page, "other");
      const card = page.locator('[data-conversation-card="t-forum"]');
      assert.ok((await card.innerText()).includes("Tuesday edition planning"));
      assert.ok((await card.innerText()).includes("7 messages"));
      const open_ = card.locator("[data-conversation-open]");
      assert.equal(await open_.getAttribute("href"), "/newsroom/forum/t-forum");
      assert.equal(await open_.locator("svg").count(), 1);
      assert.equal(await card.locator("[data-conversation-composer]").count(), 0, "answered in its own thread view");
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

  /** Flat tones and rounded rectangles: no borders, outlines or rules anywhere on the page. */
  async design() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      await page.locator('[data-conversation-card="t-general"] [data-conversation-reply="g1"]').click();
      const offenders = await page.locator("[data-conversations-view], [data-conversations-view] *").evaluateAll((elements) => elements.flatMap((element) => {
        const style = getComputedStyle(element);
        const edges = ["top", "right", "bottom", "left"].some((edge) => parseFloat(style.getPropertyValue(`border-${edge}-width`)) > 0 && style.getPropertyValue(`border-${edge}-style`) !== "none");
        const outline = parseFloat(style.outlineWidth) > 0 && style.outlineStyle !== "none";
        return edges || outline ? [element.tagName.toLowerCase() + "." + String(element.getAttribute("class")).slice(0, 40)] : [];
      }));
      assert.deepEqual(offenders, [], "no borders or outlines");
      const radius = await page.locator('[data-conversation-card="t-ref-1"]').evaluate((element) => parseFloat(getComputedStyle(element).borderTopLeftRadius));
      assert.ok(radius >= 8, "rounded rectangles");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
    });
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
