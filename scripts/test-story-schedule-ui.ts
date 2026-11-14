/**
 * Fixture-only browser acceptance for scheduled publishing in the newsroom: the schedule badge on the Stories board cards, the schedule row in the Story drawer,
 * and the Schedule page (FullCalendar 7), on the local-preview data (lib/local-preview-seed.ts: clearly fake Stories and people) and a fixed clock, in light and
 * dark at 1440 and 375 pixels. No network, no production reads. Run one scenario with `tsx scripts/test-story-schedule-ui.ts calendar`; set
 * PAPYRUS_STORY_SCHEDULE_SHOTS=<dir> to write the screenshots.
 *
 * The clock is Thursday 12 November 2026, 15:00 UTC (10:00 in New York, the publication's zone). The seed places its Stories relative to that day.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://story-schedule.test";
const CLOCK = new Date("2026-11-12T15:00:00Z");
/** Seeds of lib/local-preview-seed.ts (seededScheduleFields). */
const SCHEDULED = "preview-item-lineage-copywriting-0";   // Fri 13 Nov, 9:00 AM ET
const SECOND = "preview-item-lineage-copywriting-1";      // Sat 14 Nov, 1:00 PM ET
const OVERDUE = "preview-item-lineage-illustration-0";    // scheduled for Wed 11 Nov, 1:00 PM ET, never published
const SUPERSEDED = "preview-item-lineage-illustration-1"; // Sun 15 Nov, 8:00 AM ET (blocked: a newer version was saved)
const UNSCHEDULED = "preview-item-lineage-idea-0";
const UNSCHEDULED_TWO = "preview-item-lineage-idea-1";
const shots = process.env.PAPYRUS_STORY_SCHEDULE_SHOTS;
let bundle: Promise<string> | undefined;
let css: Promise<string> | undefined;

function stylesheet(): Promise<string> {
  css ??= (async () => {
    const file = `${root}app/tailwind.css`;
    const { default: postcss } = await import("postcss");
    const { default: tailwind } = await import("@tailwindcss/postcss");
    const tailwindCss = (await postcss([tailwind() as never]).process(fs.readFileSync(file, "utf8"), { from: file })).css;
    const bundled = await build({
      absWorkingDir: root, bundle: true, write: false, logLevel: "silent", loader: { ".woff2": "empty", ".woff": "empty" },
      entryPoints: [
        "node_modules/@kanbus/ui/dist/styles/kanban.css", "node_modules/@kanbus/ui/dist/styles/themes/index.css", "components/newsroom-theme.css", "components/newsroom-organizer.css",
        "node_modules/@fullcalendar/react/skeleton.css", "node_modules/@fullcalendar/react/themes/classic/theme.css", "components/story-schedule.css", "components/schedule-calendar.css",
      ],
      outdir: "out",
    });
    return [tailwindCss, ...bundled.outputFiles.map((output) => output.text)].join("\n");
  })();
  return css;
}

const NAVIGATION = `
import { useMemo, useSyncExternalStore } from 'react';
const listeners = new Set();
const notify = () => listeners.forEach((listener) => listener());
const subscribe = (listener) => { listeners.add(listener); window.addEventListener('popstate', listener); return () => { listeners.delete(listener); window.removeEventListener('popstate', listener); }; };
export const usePathname = () => useSyncExternalStore(subscribe, () => location.pathname);
export const useSearchParams = () => { const search = useSyncExternalStore(subscribe, () => location.search); return useMemo(() => new URLSearchParams(search), [search]); };
export const useRouter = () => useMemo(() => ({ push: (url) => { history.pushState({}, '', url); notify(); }, replace: (url) => { history.replaceState({}, '', url); notify(); } }), []);
`;
const DYNAMIC = `
import { Suspense, lazy } from 'react';
export default function dynamic(loader, options = {}) {
  const Lazy = lazy(loader);
  const Loading = options.loading;
  return (props) => <Suspense fallback={Loading ? <Loading /> : null}><Lazy {...props} /></Suspense>;
}
`;
const BOARD_CLIENT = `
import { createLocalPreviewContentItemVersions, createLocalPreviewScheduledVersions } from ${JSON.stringify(root + "lib/local-preview-seed")};
import { SCHEDULE_PAGE_STATES } from ${JSON.stringify(root + "lib/story-schedule-query")};
export const CONTENT_ITEM_COLUMN_PAGE_LIMIT = 25;
export const loadNewsroomContentItemStagePage = async (stage) => ({ versions: createLocalPreviewContentItemVersions().filter((version) => version.stage === stage), nextToken: null });
export const loadNewsroomContentItemsChangedSince = async (stage, since) => createLocalPreviewContentItemVersions().filter((version) => version.stage === stage && String(version.updatedAt ?? '') >= since);
export const loadNewsroomScheduledStories = async (from, to) => { window.fixtureRanges.push({ from, to }); return createLocalPreviewScheduledVersions(from, to, SCHEDULE_PAGE_STATES); };
export const loadNewsroomAssignmentPage = async () => ({ items: [], nextToken: null });
export const saveNewsroomAssignmentDesk = async () => undefined;
`;
const STUBS: Record<string, string> = {
  "news-desk-client-provider": "export const useOptionalNewsDeskClient = () => ({ shell: { phase: 'ready', dashboard: { newsroomSections: [] } } });",
  "newsroom-access-gate": "export const NewsDeskAccessGate = () => null;",
  "newsroom-assignment-detail": "export const NewsroomAssignmentDetail = () => null;",
  "newsroom-ops-shell": "export const NewsroomOpsShell = ({ children, headerActions, pageTitle }) => <div className='newsroom-organizer' data-kanbus-theme='newspaper-gothic' data-color-mode={document.documentElement.dataset.colorMode || 'light'} data-sidebar-collapsed='true'><div className='organizer-workspace'><header className='organizer-topbar'><h1>{pageTitle}</h1><div className='organizer-header-actions'>{headerActions}</div></header><main className='organizer-main'>{children}</main></div></div>; export const NewsroomOpsStatusBanner = ({ children }) => <p role='alert'>{children}</p>;",
};

function browserBundle(): Promise<string> {
  bundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic", logLevel: "silent",
    loader: { ".css": "empty", ".woff2": "empty", ".woff": "empty" },
    define: { "process.env.NODE_ENV": '"development"' },
    banner: { js: `window.process = { env: { NODE_ENV: "development", NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW: "1" } };` },
    plugins: [{ name: "fixture-boundaries", setup(builder) {
      builder.onResolve({ filter: /^next\/navigation$/ }, () => ({ path: "navigation", namespace: "fixture" }));
      builder.onResolve({ filter: /^next\/dynamic$/ }, () => ({ path: "dynamic", namespace: "fixture" }));
      builder.onResolve({ filter: /news-desk-taxonomy-client$/ }, (args) => /newsroom-board-view|use-paged-content-item-versions|newsroom-schedule-page/.test(args.importer) ? { path: "board-client", namespace: "fixture" } : undefined);
      builder.onResolve({ filter: new RegExp(`/(${Object.keys(STUBS).join("|")})$`) }, (args) => ({ path: args.path.split("/").pop()!, namespace: "fixture-stub" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({ contents: path === "navigation" ? NAVIGATION : path === "dynamic" ? DYNAMIC : BOARD_CLIENT, loader: "jsx", resolveDir: root }));
      builder.onLoad({ filter: /.*/, namespace: "fixture-stub" }, ({ path }) => ({ contents: STUBS[path], loader: "jsx", resolveDir: root }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "story-schedule-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { NewsroomBoardView } from "./components/newsroom-board-view";
import { NewsroomSchedulePage } from "./components/newsroom-schedule-page";
import { resolveArticlesBackend } from "./lib/newsroom-articles";
// What the backend was asked to do, and a switch that makes a schedule change fail.
window.fixtureCalls = [];
window.fixtureRanges = [];
window.fixtureFailSchedule = false;
const actions = resolveArticlesBackend(true).actions;
const scheduleStory = actions.scheduleStory;
actions.scheduleStory = async (input) => {
  window.fixtureCalls.push({ action: "scheduleStory", ...input });
  if (window.fixtureFailSchedule) throw new Error("The schedule could not be saved. Try again.");
  return scheduleStory(input);
};
for (const name of ["saveItemDraft", "publishItem", "unpublishItem", "moveStoryStage"]) {
  const original = actions[name];
  actions[name] = async (...args) => { window.fixtureCalls.push({ action: name }); return original(...args); };
}
createRoot(document.getElementById("root")).render(new URLSearchParams(location.search).get("page") === "schedule" ? <NewsroomSchedulePage /> : <NewsroomBoardView subject="contentItem" />);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

async function setup(path: string, options: { width?: number; height?: number; mode?: "light" | "dark"; timezoneId?: string } = {}) {
  const { width = 1440, height = 1000, mode = "light", timezoneId = "America/New_York" } = options;
  const script = await browserBundle();
  const styles = await stylesheet();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width, height }, timezoneId, colorScheme: mode });
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.clock.install({ time: CLOCK });
  await page.addInitScript(() => window.localStorage.setItem("papyrus:reader-settings", JSON.stringify({ motion: "low" })));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html data-color-mode="${mode}" class="${mode === "dark" ? "dark" : "light-theme"}"><head><meta name="viewport" content="width=device-width"><style>${styles}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}${path}`);
  return { browser, page, errors };
}

const board = "/newsroom/articles";
const schedulePage = "/newsroom/schedule?page=schedule";
const card = (page: Page, lineage: string) => page.locator(`.issue-card[data-issue-id="contentItem:${lineage}"]`);
const badge = (page: Page, lineage: string) => card(page, lineage).locator("[data-story-schedule] .story-schedule-badge");
const panel = (page: Page) => page.locator("[data-story-schedule-panel]");
const calls = (page: Page) => page.evaluate(() => (window as unknown as { fixtureCalls: unknown[] }).fixtureCalls);
const scheduleCalls = async (page: Page) => (await calls(page) as { action: string }[]).filter((call) => call.action === "scheduleStory");
async function openStory(page: Page, lineage: string) {
  await card(page, lineage).locator("h3").click();
  await panel(page).waitFor();
}
async function shot(page: Page, name: string) {
  if (shots) { fs.mkdirSync(shots, { recursive: true }); await page.screenshot({ path: `${shots}/${name}.png` }); }
}
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
const iconOf = (locator: ReturnType<Page["locator"]>) => locator.locator("svg").first().getAttribute("class");

/** Fill the drawer's form and press Save. */
async function fillAndSave(page: Page, date: string, time: string) {
  await panel(page).locator("[data-story-schedule-date]").fill(date);
  await panel(page).locator("[data-story-schedule-time]").fill(time);
  await panel(page).locator("[data-story-schedule-save]").click();
}

const scenarios: Record<string, () => Promise<void>> = {
  /** A scheduled, an overdue and a superseded card each say so in an icon and words; an unscheduled card says nothing. */
  async badge_states() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, { mode });
      try {
        await badge(page, SCHEDULED).waitFor();
        assert.equal(await badge(page, SCHEDULED).innerText(), "Scheduled: Fri 13 Nov, 9:00 AM ET", "the time in the publication's zone");
        assert.match(await iconOf(badge(page, SCHEDULED)) ?? "", /lucide-calendar-clock/);
        assert.equal(await badge(page, OVERDUE).innerText(), "Overdue");
        assert.match(await iconOf(badge(page, OVERDUE)) ?? "", /lucide-triangle-alert/);
        assert.equal(await badge(page, SUPERSEDED).innerText(), "Superseded: a newer version was saved");
        assert.match(await iconOf(badge(page, SUPERSEDED)) ?? "", /lucide-circle-slash/);
        assert.equal(await badge(page, UNSCHEDULED).count(), 0, "an unscheduled Story shows no badge");
        assert.match(await badge(page, OVERDUE).getAttribute("title") ?? "", /scheduled to publish Wed 11 Nov, 1:00 PM ET and has not been published/, "the title keeps every fact");
        await shot(page, `badge-${mode}-1440`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** The drawer says when the Story goes live in the publication's zone, and the editor's own zone in small type when it differs. */
  async drawer_sentence() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, { mode });
      try {
        await openStory(page, SCHEDULED);
        assert.equal(await panel(page).locator("[data-story-schedule-sentence]").innerText(), "Scheduled for Fri 13 Nov 2026, 9:00 AM ET (New York), by Preview editor");
        assert.equal(await panel(page).locator("[data-story-schedule-own]").count(), 0, "same zone: no second line");
        assert.equal(await page.locator("[data-newsroom-article-publish]").innerText(), "Publish", "Publish now stays as it was");
        assert.equal(await page.locator("[data-newsroom-article-status]").innerText(), "Draft", "and so does the published state");
        await shot(page, `drawer-${mode}-1440`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
    const london = await setup(board, { timezoneId: "Europe/London" });
    try {
      await openStory(london.page, SCHEDULED);
      assert.equal(await panel(london.page).locator("[data-story-schedule-own]").innerText(), "2:00 PM GMT your time");
      assert.equal(await panel(london.page).locator("[data-story-schedule-sentence]").innerText(), "Scheduled for Fri 13 Nov 2026, 9:00 AM ET (New York), by Preview editor");
    } finally { await london.browser.close(); }
  },

  /** An editor sets a time, the drawer and the card show it, and clearing it takes both back. Only schedule changes are sent. */
  async set_and_clear() {
    const { browser, page, errors } = await setup(board);
    try {
      await openStory(page, UNSCHEDULED);
      assert.match(await panel(page).locator("[data-story-schedule-none]").innerText(), /^Not scheduled\./);
      await panel(page).locator("[data-story-schedule-open]").click();
      await fillAndSave(page, "2026-11-20", "07:30");
      await panel(page).locator("[data-story-schedule-sentence]").waitFor();
      assert.equal(await panel(page).locator("[data-story-schedule-sentence]").innerText(), "Scheduled for Fri 20 Nov 2026, 7:30 AM ET (New York), by Preview editor");
      assert.deepEqual(await calls(page), [{ action: "scheduleStory", itemId: "preview-item-version-idea-0", lineageId: UNSCHEDULED, scheduledPublishAt: "2026-11-20T12:30:00.000Z" }], "the version and the UTC instant are sent, nothing else is");
      await badge(page, UNSCHEDULED).waitFor();
      assert.equal(await badge(page, UNSCHEDULED).innerText(), "Scheduled: Fri 20 Nov, 7:30 AM ET", "the card follows");
      // Change it.
      await panel(page).locator("[data-story-schedule-open]").click();
      assert.equal(await panel(page).locator("[data-story-schedule-time]").inputValue(), "07:30", "the form starts from the saved time");
      await fillAndSave(page, "2026-11-21", "14:00");
      await page.waitForFunction(() => document.querySelector("[data-story-schedule-sentence]")?.textContent?.includes("Sat 21 Nov 2026, 2:00 PM"));
      // Clear it.
      await panel(page).locator("[data-story-schedule-clear]").click();
      await panel(page).locator("[data-story-schedule-none]").waitFor();
      await page.waitForFunction((lineage) => !document.querySelector(`.issue-card[data-issue-id="contentItem:${lineage}"] [data-story-schedule]`), UNSCHEDULED);
      assert.deepEqual((await scheduleCalls(page)).map((call) => (call as unknown as { scheduledPublishAt: string | null }).scheduledPublishAt), ["2026-11-20T12:30:00.000Z", "2026-11-21T19:00:00.000Z", null]);
      assert.deepEqual((await calls(page) as { action: string }[]).filter((call) => call.action !== "scheduleStory"), [], "no draft save, publish or stage move");
      assert.equal(await page.locator("[data-newsroom-article-status]").innerText(), "Draft");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A change the backend refuses shows what was saved again, says why, and keeps what the editor typed in the form. */
  async failed_save() {
    const { browser, page, errors } = await setup(board);
    try {
      await openStory(page, SCHEDULED);
      await page.evaluate(() => { (window as unknown as { fixtureFailSchedule: boolean }).fixtureFailSchedule = true; });
      await panel(page).locator("[data-story-schedule-open]").click();
      await fillAndSave(page, "2026-11-25", "10:15");
      await panel(page).locator("[data-story-schedule-problem]").waitFor();
      assert.equal(await panel(page).locator("[data-story-schedule-problem]").innerText(), "The schedule could not be saved. Try again.");
      assert.equal(await panel(page).locator("[data-story-schedule-sentence]").innerText(), "Scheduled for Fri 13 Nov 2026, 9:00 AM ET (New York), by Preview editor", "the saved time is shown again");
      assert.equal(await panel(page).locator("[data-story-schedule-date]").inputValue(), "2026-11-25", "what was typed stays");
      assert.equal(await panel(page).locator("[data-story-schedule-time]").inputValue(), "10:15");
      await page.evaluate(() => { (window as unknown as { fixtureFailSchedule: boolean }).fixtureFailSchedule = false; });
      await panel(page).locator("[data-story-schedule-save]").click();
      await page.waitForFunction(() => document.querySelector("[data-story-schedule-sentence]")?.textContent?.includes("Wed 25 Nov 2026, 10:15 AM"));
      assert.equal(await panel(page).locator("[data-story-schedule-problem]").count(), 0);
      // A time that has passed is refused before anything is sent.
      const sent = (await scheduleCalls(page)).length;
      await panel(page).locator("[data-story-schedule-open]").click();
      await fillAndSave(page, "2026-11-10", "09:00");
      assert.match(await panel(page).locator("[data-story-schedule-problem]").innerText(), /^That time has passed\./);
      assert.equal((await scheduleCalls(page)).length, sent, "nothing was sent");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A time that does not exist is refused in plain words; a time that happens twice asks which one. */
  async dst() {
    const { browser, page, errors } = await setup(board);
    try {
      await openStory(page, UNSCHEDULED_TWO);
      await panel(page).locator("[data-story-schedule-open]").click();
      await fillAndSave(page, "2027-03-14", "02:30");
      assert.equal(await panel(page).locator("[data-story-schedule-problem]").innerText(), "That time does not exist on 14 March in New York. Pick another time.");
      assert.equal((await scheduleCalls(page)).length, 0, "nothing was sent");
      await fillAndSave(page, "2027-11-07", "01:30");
      assert.match(await panel(page).locator("[data-story-schedule-problem]").innerText(), /happens twice/);
      const labels = await panel(page).locator("[data-story-schedule-choices] label").allInnerTexts();
      assert.deepEqual(labels.map((label) => label.trim()), ["01:30 EDT", "01:30 EST"], "both, earlier first");
      assert.equal((await scheduleCalls(page)).length, 0, "and nothing was sent until one is chosen");
      await panel(page).locator("[data-story-schedule-choices] label", { hasText: "EST" }).locator("input").check();
      await panel(page).locator("[data-story-schedule-save]").click();
      await panel(page).locator("[data-story-schedule-sentence]").waitFor();
      assert.deepEqual(await scheduleCalls(page), [{ action: "scheduleStory", itemId: "preview-item-version-idea-1", lineageId: UNSCHEDULED_TWO, scheduledPublishAt: "2027-11-07T06:30:00.000Z" }], "the second 01:30, which is 06:30 UTC");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** The Schedule page: the week in New York time with icon, state and title; Day and Month; a plain list; an empty state; keyboard access; and only a range is read. */
  async calendar() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(schedulePage, { mode });
      try {
        await page.locator("[data-schedule-item]").first().waitFor();
        assert.match(await page.locator("[data-schedule-zone]").innerText(), /New York time/);
        const events = page.locator("[data-schedule-calendar] .schedule-event");
        const text = (await events.allInnerTexts()).map((entry) => entry.replace(/\s+/g, " ").trim());
        assert.deepEqual(text.map((entry) => entry.replace(/ (News|Features)$/i, "")), [
          "1:00 PM Overdue Layout pass: front page lead and rail",
          "9:00 AM Scheduled Illustration brief: flooded streets, aerial view",
          "1:00 PM Scheduled Illustration brief: the market at dawn",
        ].map((entry) => entry), "the week, in New York time (9:00 AM is 14:00 UTC), each with its state in words and its title");
        assert.equal(await events.evaluateAll((nodes) => nodes.every((node) => node.querySelector("svg"))), true, "every event has an icon");
        assert.equal(await page.locator("[data-schedule-list] [data-schedule-item]").count(), 3, "the same three in the list");
        assert.equal(await page.locator("[data-schedule-empty]").count(), 0);
        await shot(page, `calendar-week-${mode}-1440`);
        // Day, then Month.
        await page.getByRole("tab", { name: "Month view" }).click();
        await page.waitForFunction(() => document.querySelectorAll("[data-schedule-item]").length === 4);
        await shot(page, `calendar-month-${mode}-1440`);
        await page.getByRole("tab", { name: "Day view" }).click();
        await page.locator("[data-schedule-empty]").waitFor();
        assert.match(await page.locator("[data-schedule-empty]").innerText(), /^Nothing is scheduled today\./);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
    const { browser, page, errors } = await setup(schedulePage);
    try {
      await page.locator("[data-schedule-item]").first().waitFor();
      // Only the range on screen is read, a week and then the next week.
      await page.getByRole("button", { name: "Next Week" }).click();
      await page.waitForFunction(() => (window as unknown as { fixtureRanges: unknown[] }).fixtureRanges.length >= 2);
      const ranges = await page.evaluate(() => (window as unknown as { fixtureRanges: { from: string; to: string }[] }).fixtureRanges);
      assert.deepEqual(ranges.map((range) => (Date.parse(range.to) - Date.parse(range.from)) / 86_400_000), [7, 7], "one week at a time");
      assert.equal(ranges[0].from, "2026-11-08T05:00:00.000Z", "from the publication's midnight (05:00 UTC)");
      await page.getByRole("button", { name: "Next Week" }).click();
      await page.locator("[data-schedule-empty]").waitFor();
      assert.match(await page.locator("[data-schedule-empty]").innerText(), /Nothing is scheduled this week\.[\s\S]*Schedule a Story/);
      assert.equal(await page.locator("[data-schedule-empty] a").getAttribute("href"), "/newsroom/stories", "Schedule a Story opens the Stories board");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Events take the keyboard, a plain list follows the calendar, and Enter on an event opens its Story. */
  async keyboard() {
    const { browser, page, errors } = await setup(schedulePage);
    try {
      await page.locator("[data-schedule-item]").first().waitFor();
      const focusable = page.locator('[data-schedule-calendar] [role="button"][tabindex="0"]');
      assert.equal(await focusable.count(), 3, "every event is a focusable button");
      const links = page.locator("[data-schedule-list] a");
      assert.equal(await links.count(), 3);
      const first = (await links.first().getAttribute("href")) ?? "";
      assert.match(first, /^\/newsroom\/articles\//);
      await focusable.first().focus();
      await page.keyboard.press("Enter");
      await page.waitForFunction(() => location.pathname.startsWith("/newsroom/articles/"));
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** On a phone the week is a list by day, nothing scrolls sideways, and the drawer's schedule row fits. */
  async phone() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(schedulePage, { width: 375, height: 900, mode });
      try {
        await page.locator("[data-schedule-item]").first().waitFor();
        assert.equal(await page.locator("[data-schedule-calendar]").getAttribute("data-schedule-layout"), "list");
        assert.equal(await page.locator("[data-schedule-calendar] .schedule-event").count(), 3);
        assert.equal(await noSideScroll(page), true, "calendar: nothing scrolls sideways");
        await shot(page, `calendar-${mode}-375`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
      const onBoard = await setup(board, { width: 375, height: 900, mode });
      try {
        await badge(onBoard.page, SCHEDULED).waitFor();
        await badge(onBoard.page, SCHEDULED).scrollIntoViewIfNeeded();
        assert.equal(await noSideScroll(onBoard.page), true, "board: nothing scrolls sideways");
        await shot(onBoard.page, `badge-${mode}-375`);
        await openStory(onBoard.page, SCHEDULED);
        await panel(onBoard.page).scrollIntoViewIfNeeded();
        await panel(onBoard.page).locator("[data-story-schedule-open]").click();
        await panel(onBoard.page).locator("[data-story-schedule-form]").scrollIntoViewIfNeeded();
        assert.equal(await noSideScroll(onBoard.page), true, "drawer: nothing scrolls sideways");
        const clipped = await onBoard.page.evaluate(`(function(){var out=[];var els=document.querySelectorAll('[data-story-schedule-panel], [data-story-schedule-panel] *');for(var i=0;i<els.length;i++){var r=els[i].getBoundingClientRect();if(r.width>0&&(r.right>window.innerWidth+1||r.left<-1)){out.push(els[i].tagName+'.'+els[i].className);}}return out.slice(0,5);})()`) as string[];
        assert.deepEqual(clipped, [], "nothing in the schedule row runs past the screen's edge");
        const heights = await panel(onBoard.page).locator("button, input").evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().height));
        assert.ok(heights.every((height) => height >= 36), `phone targets are at least 36px tall: ${heights}`);
        await shot(onBoard.page, `drawer-${mode}-375`);
        assert.deepEqual(onBoard.errors, []);
      } finally { await onBoard.browser.close(); }
    }
  },

  /** Flat fills and rounded shapes: no visible outline on the badge, the drawer row or the calendar, in light and dark. */
  async no_borders() {
    for (const mode of ["light", "dark"] as const) {
      const sample = `(function(){
        var page=document.querySelector('.newsroom-organizer');var bg=getComputedStyle(page).backgroundColor;var bad=[];
        var els=document.querySelectorAll('[data-schedule-page] *, [data-story-schedule-panel], [data-story-schedule-panel] *, .story-schedule-badge');
        for(var i=0;i<els.length;i++){var s=getComputedStyle(els[i]);
          ['Top','Right','Bottom','Left'].forEach(function(side){
            if(s['border'+side+'Style']!=='none'&&parseFloat(s['border'+side+'Width'])>0&&s['border'+side+'Color']!=='rgba(0, 0, 0, 0)'&&s['border'+side+'Color']!==bg&&s['border'+side+'Color']!==s.backgroundColor){bad.push(els[i].tagName+'.'+String(els[i].className).slice(0,40)+' '+side+' '+s['border'+side+'Color']);}
          });}
        return bad.slice(0,8);})()`;
      const onPage = await setup(schedulePage, { mode });
      try {
        await onPage.page.locator("[data-schedule-item]").first().waitFor();
        assert.deepEqual(await onPage.page.evaluate(sample), [], `calendar page (${mode}): every border is the page colour or the element's own fill`);
        await onPage.page.getByRole("tab", { name: "Month view" }).click();
        await onPage.page.waitForFunction(() => document.querySelectorAll("[data-schedule-item]").length === 4);
        assert.deepEqual(await onPage.page.evaluate(sample), [], `month view (${mode})`);
      } finally { await onPage.browser.close(); }
      const onBoard = await setup(board, { mode });
      try {
        await openStory(onBoard.page, SCHEDULED);
        await onBoard.page.locator("[data-story-schedule-open]").click();
        assert.deepEqual(await onBoard.page.evaluate(sample), [], `drawer (${mode})`);
      } finally { await onBoard.browser.close(); }
    }
  },
};

void (async () => {
  const wanted = process.argv[2] ?? "all";
  for (const name of wanted === "all" ? Object.keys(scenarios) : [wanted]) {
    assert(scenarios[name], `unknown scenario ${name}`);
    await scenarios[name]();
    console.log(`Story schedule scenario passed: ${name}`);
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
