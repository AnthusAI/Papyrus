/** Fixture-only browser acceptance for Messages on a Reference at 375 and 1440 pixels. No network beyond the fixture origin, no production reads. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://conversations.test";
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
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "conversations-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { useMemo, useState } from "react";
import { ReferenceFeed } from "./components/reference-feed";
import { ReviewCard } from "./components/reference-review-card";
import { ReferenceConversation } from "./components/reference-conversation";
import { ConversationStoreProvider, createMemoryConversationStore } from "./components/conversation-context";
import { partitionReferenceFeed } from "./lib/reference-feed-ranking";

const params = new URLSearchParams(location.search);
const minutesAgo = (minutes) => new Date(Date.now() - minutes * 60000).toISOString();
const message = (sequenceNumber, parentMessageId, authorLabel, content, minutes) => ({ id: "m" + sequenceNumber, parentMessageId, authorLabel, content, createdAt: minutesAgo(minutes), sequenceNumber });
const SEEDS = {
  none: [],
  root: [message(1, null, "ada@example.test", "This could anchor the Tuesday explainer.", 50)],
  nested: [
    message(1, null, "ada@example.test", "This could anchor the Tuesday explainer.", 50),
    message(2, "m1", "grace@example.test", "Agreed, but check the date range first.", 30),
    message(3, "m2", "ada@example.test", "Checked: the range is fine.", 10),
    message(4, null, "grace@example.test", "A second thought, unrelated to the first.", 5),
  ],
};
const REFERENCE = { lineageId: "ref-1", id: "ref-1-v1", title: "Fixture reference about water policy" };
const memory = createMemoryConversationStore("you@example.test", { ["reference#" + REFERENCE.lineageId]: SEEDS[params.get("seed") || "none"] });
window.calls = [];
const store = {
  ...memory,
  append: async (input) => {
    window.calls.push({ type: "append", body: input.body, parentMessageId: input.parentMessageId, anchor: input.anchor.kind + "#" + input.anchor.lineageId });
    await new Promise((resolve) => setTimeout(resolve, params.has("slow") ? 700 : 20));
    if (params.has("fail")) throw new Error("The backend refused this.");
    return memory.append(input);
  },
};

const NOW = Date.now();
const make = (id, fields = {}) => ({ id: id + "-v1", lineageId: id, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: id, title: "Title of " + id, sourceUri: "https://" + id + ".example.org/story", curationStatus: "pending", createdAt: new Date(NOW - 3600000).toISOString(), sourcePublishedAt: new Date(NOW - 3600000).toISOString(), ...fields });
const FIXTURE = [make("with-messages"), make("one-message"), make("no-messages")];
const COUNTS = new Map([["with-messages", 3], ["one-message", 1]]);

function Detail() {
  const [count, setCount] = useState(null);
  return <div className="max-w-xl space-y-4" data-fixture-detail>
    <ReviewCard decided={null} itemId={REFERENCE.lineageId} onDecide={async () => undefined} prediction={{ state: "none" }} title={REFERENCE.title} dek="A one line dek for the Reference.">
      <ReferenceConversation lineageId={REFERENCE.lineageId} onCount={(_id, n) => { window.reportedCount = n; setCount(n); }} referenceId={REFERENCE.id} title={REFERENCE.title} />
    </ReviewCard>
    <p data-fixture-count>{count === null ? "" : count}</p>
  </div>;
}

function Feed() {
  const partition = useMemo(() => partitionReferenceFeed(FIXTURE, new Map(), { now: NOW, visitRated: new Set(), tauDaysOverride: null }), []);
  return <ReferenceFeed messageCounts={COUNTS} now={NOW} onOpen={() => undefined} onRate={async () => undefined} onTabChange={() => undefined} onVisitRated={() => undefined} partition={partition} previews={new Map()} tab="feed" visitRated={new Set()} />;
}

createRoot(document.getElementById("root")).render(<ConversationStoreProvider store={store}>{params.has("feed") ? <Feed /> : <Detail />}</ConversationStoreProvider>);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

// The tones the newsroom stylesheet mixes from the publication theme, as plain colours here.
const fixtureCss = "body{margin:0;font:16px sans-serif;background:#f4f1ea;color:#1c1c1c;--feed-card:#fbf9f4;--feed-control:#e8e3d8;--feed-footer:#f0ece2;--feed-radius-lg:12px;--feed-radius-pill:999px;--primary:#46560f;--primary-foreground:#fff}button,textarea{font:inherit}";

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

const thread = (page: Page) => page.locator("[data-conversation-thread]");
const calls = (page: Page) => page.evaluate(() => (window as unknown as { calls: unknown[] }).calls);
const composer = (page: Page) => page.locator('[data-conversation-composer="post"] textarea');

async function screenshot(page: Page, name: string, width: number) {
  if (shots) await page.screenshot({ path: `${shots}/${name}-${width}.png`, fullPage: true });
}

const scenarios: Record<string, () => Promise<void>> = {
  /** A message written on a Reference shows at once, as the signed-in author, and is saved against that Reference. */
  async post() {
    await run("?slow=1", [375, 1440], async (page, width) => {
      await thread(page).waitFor();
      await page.locator("[data-conversation-empty]").waitFor();
      const post = page.locator('[data-conversation-post="post"]');
      assert.equal(await post.isDisabled(), true, "nothing to post yet");
      assert.equal(await post.locator("svg").count(), 1, "a Lucide icon on the button");
      await composer(page).fill("Worth a closer look for the housing story.");
      await post.click();
      const sending = page.locator("[data-conversation-pending]");
      await sending.waitFor();
      assert.ok((await sending.innerText()).includes("Sending"), "the message shows at once, marked as sending in words");
      assert.equal(await composer(page).inputValue(), "", "the box clears when you post");
      await page.locator("[data-conversation-pending]").waitFor({ state: "detached" });
      const posted = page.locator("[data-conversation-message]");
      assert.equal(await posted.count(), 1);
      assert.equal(await posted.locator("[data-conversation-author]").innerText(), "you", "the author, not the full address");
      assert.equal(await posted.locator("[data-conversation-content]").innerText(), "Worth a closer look for the housing story.");
      assert.deepEqual(await calls(page), [{ type: "append", body: "Worth a closer look for the housing story.", parentMessageId: null, anchor: "reference#ref-1" }]);
      assert.equal(await page.locator("[data-fixture-count]").innerText(), "1", "the count follows the conversation");
      await screenshot(page, "post", width);
    });
  },

  /** Reply opens the same box under the message, and the reply nests under it. */
  async reply() {
    await run("?seed=root", [375, 1440], async (page, width) => {
      await page.locator('[data-conversation-message="m1"]').waitFor();
      const reply = page.locator('[data-conversation-reply="m1"]');
      assert.equal(await reply.locator("svg").count(), 1, "a Lucide icon on Reply");
      assert.ok((await reply.innerText()).includes("Reply"), "and the word");
      await reply.click();
      const box = page.locator('[data-conversation-composer="reply"] textarea');
      await box.fill("Let us draft it Monday.");
      await page.locator('[data-conversation-post="reply"]').click();
      await page.locator("[data-conversation-replies] [data-conversation-message]").waitFor();
      await page.locator("[data-conversation-pending]").waitFor({ state: "detached" });
      assert.equal(await page.locator("[data-conversation-replies] [data-conversation-content]").innerText(), "Let us draft it Monday.", "nested under the message");
      assert.equal(await page.locator("[data-conversation-answers]").count(), 0, "a reply to a top-level message needs no label");
      assert.deepEqual(await calls(page), [{ type: "append", body: "Let us draft it Monday.", parentMessageId: "m1", anchor: "reference#ref-1" }]);
      assert.equal(await page.locator('[data-conversation-composer="reply"]').count(), 0, "the reply box closes once posted");
      await screenshot(page, "reply", width);
    });
  },

  /** A reply to a reply stays flat under the same top-level message and says who it answers. */
  async flat() {
    await run("?seed=nested", [375, 1440], async (page, width) => {
      await page.locator('[data-conversation-message="m3"]').waitFor();
      const roots = await page.locator("[data-conversation-thread] > ul > li").count();
      assert.equal(roots, 2, "two top-level messages");
      const first = page.locator("[data-conversation-thread] > ul > li").first();
      assert.deepEqual(await first.locator("[data-conversation-replies] [data-conversation-message]").evaluateAll((items) => items.map((item) => item.getAttribute("data-conversation-message"))), ["m2", "m3"], "both replies sit under the first message, one level deep");
      assert.equal(await first.locator("[data-conversation-replies] [data-conversation-replies]").count(), 0, "never nested deeper");
      const label = page.locator('[data-conversation-message="m3"] [data-conversation-answers]');
      assert.ok((await label.innerText()).includes("In reply to grace"), "labelled with who it answers");
      assert.equal(await label.locator("svg").count(), 1, "with an icon");
      await page.locator('[data-conversation-reply="m3"]').click();
      await page.locator('[data-conversation-composer="reply"] textarea').fill("Thanks.");
      await page.locator('[data-conversation-post="reply"]').click();
      await page.locator("[data-conversation-pending]").waitFor({ state: "detached" });
      assert.deepEqual((await calls(page)) as unknown[], [{ type: "append", body: "Thanks.", parentMessageId: "m3", anchor: "reference#ref-1" }]);
      assert.equal(await first.locator("[data-conversation-replies] > li").count(), 3, "the reply to a reply lands under the same root");
      await screenshot(page, "nested", width);
    });
  },

  /** A refused save takes the message back, says so in words with an icon, and keeps the typed text. */
  async failure() {
    await run("?seed=root&fail=1", [375, 1440], async (page, width) => {
      await thread(page).waitFor();
      await composer(page).fill("This text must survive.");
      await page.locator('[data-conversation-post="post"]').click();
      const alert = page.locator("[data-conversation-error]");
      await alert.waitFor();
      assert.ok((await alert.innerText()).includes("Not posted: The backend refused this."), "said in words");
      assert.equal(await alert.locator("svg").count(), 1, "with an icon, not colour alone");
      assert.equal(await composer(page).inputValue(), "This text must survive.", "the typed text is kept");
      assert.equal(await page.locator("[data-conversation-message]").count(), 1, "the unsaved message is not left in the list");
      await screenshot(page, "failure", width);
    });
  },

  /** A feed card shows how many messages the Reference has, as an icon and a number, and none when there are none. */
  async count() {
    await run("?feed=1", [375, 1440], async (page) => {
      await page.locator('[data-feed-card="with-messages"]').waitFor();
      const badge = page.locator('[data-feed-card="with-messages"] [data-feed-message-count]');
      assert.equal(await badge.getAttribute("aria-label"), "3 messages");
      assert.equal((await badge.innerText()).trim(), "3");
      assert.equal(await badge.locator("svg").count(), 1, "a Lucide icon beside the number");
      assert.equal(await page.locator('[data-feed-card="one-message"] [data-feed-message-count]').getAttribute("aria-label"), "1 message");
      assert.equal(await page.locator('[data-feed-card="no-messages"] [data-feed-message-count]').count(), 0, "no count when there are no messages");
    });
  },

  /** Flat tones and rounded rectangles: no borders, outlines or rules anywhere in the conversation. */
  async design() {
    await run("?seed=nested", [375, 1440], async (page, width) => {
      await page.locator('[data-conversation-message="m3"]').waitFor();
      await page.locator('[data-conversation-reply="m1"]').click();
      const offenders = await page.locator("[data-conversation-thread], [data-conversation-thread] *").evaluateAll((elements) => elements.flatMap((element) => {
        const style = getComputedStyle(element);
        const edges = ["top", "right", "bottom", "left"].some((edge) => parseFloat(style.getPropertyValue(`border-${edge}-width`)) > 0 && style.getPropertyValue(`border-${edge}-style`) !== "none");
        const outline = parseFloat(style.outlineWidth) > 0 && style.outlineStyle !== "none";
        return edges || outline ? [element.tagName.toLowerCase() + "." + String(element.getAttribute("class")).slice(0, 40)] : [];
      }));
      assert.deepEqual(offenders, [], "no borders or outlines in the conversation");
      assert.equal(await page.locator("[data-conversation-thread] select").count(), 0, "no drop-downs");
      const radius = await page.locator('[data-conversation-message="m1"]').evaluate((element) => parseFloat(getComputedStyle(element).borderTopLeftRadius));
      assert.ok(radius >= 8, "rounded rectangles");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
      await screenshot(page, "design", width);
    });
  },
};

async function main() {
  const requested = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested && requested !== name) continue;
    await scenario();
    console.log(`Conversations scenario passed: ${name}`);
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
