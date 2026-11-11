import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  applyChangedVersions,
  BOARD_REFRESH_INTERVAL_MILLISECONDS,
  newestUpdatedAt,
  startBoardRefresh,
  type VersionBucket,
} from "../lib/board-refresh";
import type { ContentItemVersionRecord } from "../lib/content-item-lifecycle";

/** A fake clock, tab and window: timers fire only when the test advances time, and a hidden tab fires nothing. */
function fakeTab() {
  let time = 0;
  let visibility: "visible" | "hidden" = "visible";
  const timers = new Map<number, { callback: () => void; every: number; due: number }>();
  let nextTimer = 1;
  let timersCreated = 0;
  const documentListeners = new Map<string, Array<() => void>>();
  const windowListeners = new Map<string, Array<() => void>>();
  const listen = (map: Map<string, Array<() => void>>) => ({
    addEventListener: (name: string, listener: () => void) => { map.set(name, [...(map.get(name) ?? []), listener]); },
    removeEventListener: (name: string, listener: () => void) => { map.set(name, (map.get(name) ?? []).filter(candidate => candidate !== listener)); },
  });
  const calls: number[] = [];
  const settle = () => new Promise(resolve => setImmediate(resolve));
  const controller = (extra: { refresh?: () => Promise<unknown> } = {}) => startBoardRefresh({
    refresh: extra.refresh ?? (async () => { calls.push(time); }),
    now: () => time,
    visibility: { get visibilityState() { return visibility; }, ...listen(documentListeners) } as unknown as Document,
    focus: listen(windowListeners) as unknown as Window,
    setTimer: (callback, every) => { const id = nextTimer++; timersCreated++; timers.set(id, { callback, every, due: time + every }); return id; },
    clearTimer: (id) => { timers.delete(id as number); },
  });
  return {
    calls, controller, settle,
    get liveTimers() { return timers.size; },
    get timersCreated() { return timersCreated; },
    async advance(milliseconds: number) {
      const end = time + milliseconds;
      for (;;) {
        const due = [...timers.values()].filter(timer => timer.due <= end).sort((left, right) => left.due - right.due)[0];
        if (!due) break;
        time = due.due; due.due += due.every; due.callback(); await settle();
      }
      time = end;
    },
    async setVisibility(next: "visible" | "hidden") { visibility = next; for (const listener of documentListeners.get("visibilitychange") ?? []) listener(); await settle(); },
    async focus() { for (const listener of windowListeners.get("focus") ?? []) listener(); await settle(); },
  };
}

const MINUTE = 60_000;

test("one timer refreshes every five minutes, not every thirty seconds", async () => {
  assert.equal(BOARD_REFRESH_INTERVAL_MILLISECONDS, 5 * MINUTE);
  const tab = fakeTab();
  const board = tab.controller();
  assert.equal(tab.liveTimers, 1, "a single timer serves the whole board");
  await tab.advance(4 * MINUTE + 59_000);
  assert.deepEqual(tab.calls, [], "nothing refreshes before five minutes");
  await tab.advance(1_000);
  assert.deepEqual(tab.calls, [5 * MINUTE]);
  await tab.advance(60 * MINUTE);
  assert.equal(tab.calls.length, 13, "twelve more in the next hour");
  board.stop();
  assert.equal(tab.liveTimers, 0, "stopping clears the timer");
});

test("the timer is paused while the tab is hidden and a visible tab refreshes once if it is stale", async () => {
  const tab = fakeTab();
  tab.controller();
  await tab.setVisibility("hidden");
  assert.equal(tab.liveTimers, 0, "no timer runs in a hidden tab");
  await tab.advance(30 * MINUTE);
  assert.deepEqual(tab.calls, [], "a hidden tab makes no requests");
  await tab.setVisibility("visible");
  assert.equal(tab.liveTimers, 1);
  assert.deepEqual(tab.calls, [30 * MINUTE], "coming back after half an hour refreshes at once, once");
  await tab.advance(5 * MINUTE);
  assert.equal(tab.calls.length, 2, "the timer counts five minutes from the return");
});

test("quick tab switching and focus changes do not hammer the backend", async () => {
  const tab = fakeTab();
  tab.controller();
  await tab.advance(10 * MINUTE);
  const before = tab.calls.length;
  for (let switches = 0; switches < 10; switches++) {
    await tab.setVisibility("hidden"); await tab.setVisibility("visible"); await tab.focus();
  }
  assert.equal(tab.calls.length, before + 0, "a refresh a moment ago is recent enough");
  await tab.advance(61_000);
  await tab.focus();
  assert.equal(tab.calls.length, before + 1, "focus after a minute of quiet refreshes");
  await tab.focus();
  assert.equal(tab.calls.length, before + 1, "and a second focus right after does not");
});

test("the user's own action refreshes now, and overlapping refreshes run one after the other", async () => {
  const tab = fakeTab();
  let release: () => void = () => undefined;
  let started = 0;
  const board = tab.controller({ refresh: () => { started++; return new Promise<void>(resolve => { release = resolve; }); } });
  board.refreshNow();
  await tab.settle();
  assert.equal(started, 1, "an action refreshes without waiting for the gap");
  board.refreshNow(); board.refreshNow();
  await tab.settle();
  assert.equal(started, 1, "a refresh already running is not doubled");
  release(); await tab.settle(); await tab.settle();
  assert.equal(started, 2, "one more runs after it, so the edit made meanwhile is shown");
  release();
  board.stop();
});

test("a failed refresh does not stop the next one", async () => {
  const tab = fakeTab();
  let attempts = 0;
  tab.controller({ refresh: async () => { attempts++; if (attempts === 1) throw new Error("offline"); } });
  await tab.advance(10 * MINUTE);
  assert.equal(attempts, 2);
});

const row = (id: string, stage: string, updatedAt: string): ContentItemVersionRecord => (
  { id, lineageId: id, versionNumber: 1, stage, type: "article", status: "draft", title: id, slug: id, updatedAt }
);
const bucket = (...versions: ContentItemVersionRecord[]): VersionBucket => ({ versions, nextToken: "more", pagesLoaded: 2 });

test("the place to read from is the newest updatedAt in a stage", () => {
  assert.equal(newestUpdatedAt([]), null);
  assert.equal(newestUpdatedAt([row("a", "idea", "2026-11-01T10:00:00.000Z"), row("b", "idea", "2026-11-03T10:00:00.000Z"), row("c", "idea", "2026-11-02T10:00:00.000Z")]), "2026-11-03T10:00:00.000Z");
});

test("changed rows replace their old copy, newest first, and keep the loaded pages", () => {
  const before = { idea: bucket(row("b", "idea", "2026-11-03T00:00:00Z"), row("a", "idea", "2026-11-01T00:00:00Z")) };
  const after = applyChangedVersions(before, { idea: [row("a", "idea", "2026-11-05T00:00:00Z"), row("n", "idea", "2026-11-04T00:00:00Z")] });
  assert.deepEqual(after.idea.versions.map(version => version.id), ["a", "n", "b"]);
  assert.equal(after.idea.versions[0].updatedAt, "2026-11-05T00:00:00Z", "the new copy is the one shown");
  assert.equal(after.idea.nextToken, "more");
  assert.equal(after.idea.pagesLoaded, 2);
});

test("a story that moved stage leaves its old column", () => {
  const before = { idea: bucket(row("a", "idea", "2026-11-01T00:00:00Z")), reporting: bucket(row("r", "reporting", "2026-11-01T00:00:00Z")) };
  const after = applyChangedVersions(before, { idea: [], reporting: [row("a", "reporting", "2026-11-05T00:00:00Z")] });
  assert.deepEqual(after.idea.versions, []);
  assert.deepEqual(after.reporting.versions.map(version => version.id), ["a", "r"]);
});

test("a quiet refresh changes nothing and keeps the same object, so the board does not redraw", () => {
  const before = { idea: bucket(row("a", "idea", "2026-11-01T00:00:00Z")), published: bucket() };
  assert.equal(applyChangedVersions(before, { idea: [], published: [] }), before);
});

test("the board has one timer, no separate published scan, and asks each stage only for changes", () => {
  const view = readFileSync("components/newsroom-board-view.tsx", "utf8");
  const hook = readFileSync("components/use-paged-content-item-versions.ts", "utf8");
  const client = readFileSync("components/news-desk-taxonomy-client.ts", "utf8") + readFileSync("lib/story-stage-query.ts", "utf8");
  assert.doesNotMatch(hook, /setInterval|visibilitychange/, "the paged hook owns no timer");
  assert.doesNotMatch(view, /setInterval|30_000/, "the board view sets no timer of its own");
  assert.equal((view.match(/startBoardRefresh\(/g) ?? []).length, 1, "one scheduler for the board");
  assert.doesNotMatch(view + hook + client, /listPublishedItems|loadNewsroomPublishedContentItemVersions/, "the duplicate published scan is gone");
  assert.match(hook, /loadNewsroomContentItemsChangedSince/);
  assert.match(client, /updatedAt: \{ ge: since \}/, "changes are read with a key condition on the stage index's sort key");
});
