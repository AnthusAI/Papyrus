/** Fixture-only browser acceptance for the References feed at 375 and 1440 pixels. No network beyond the fixture origin, no production reads. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

declare global { interface Window { requests: Array<{ kind: string; sort?: string; limit?: number; ids?: string[]; key?: string }>; site: any[]; searches: Array<{ query: string; show: string; limit: number; cursor: string | null; sort?: string; minStars?: number | null; captured?: string }> } }

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://reference-feed.test";
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
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "reference-feed-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ReferenceFeed } from "./components/reference-feed";
import { ReferencesPageLoading } from "./components/references-page-loading";
import { useFeedPreferences } from "./components/use-feed-preferences";
import { applyFeedOrderSnapshot, buildFeedItems, takeFeedOrderSnapshot } from "./lib/reference-feed-ranking";
import { useReferencePredictions } from "./lib/use-reference-predictions";
import { useFeedWindow } from "./components/use-feed-window";
import { currentRelevanceDecisions } from "./lib/relevance-decisions";
import { useFeedSearch, useIndexedReferenceFeed } from "./components/use-indexed-reference-feed";
import { previewSearch } from "./lib/reference-search";
import { scoreFeedItem, feedLeadId } from "./lib/reference-feed-ranking";
import { predictionSortKeyFor } from "./lib/reference-feed-keys";
import { compareFeedRecords, feedReaderFromRecords, starReaderFromRecords } from "./lib/reference-feed-pages";
import { useFeedControls } from "./components/use-feed-controls";
import { mediumReaderFromRecords } from "./lib/reference-medium-feed";

const params = new URLSearchParams(location.search);
const NOW = Date.parse("2026-10-27T12:00:00Z");
const DAY = 86400000;
const ago = (days) => new Date(NOW - days * DAY).toISOString();
const decision = (label, confidence) => ({ decisionRelationId: "r", decisionId: "d", label, confidence, version: 1, reviewRecommended: false, reviewReason: null, reviewDetail: null,
  classes: ["include", "exclude"], positiveLabel: "include", question: null, reviewControl: "thumbs", cyclotronId: "c", decidedAt: null, provenance: null });
let made = 0;
const make = (id, fields = {}) => ({ id: id + "-v1", lineageId: id, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: id, title: "Title of " + id, sourceUri: "https://" + id + ".example.org/story", curationStatus: "pending", createdAt: ago(0.4 + 0.01 * (made += 1)), sourcePublishedAt: ago(0.4), ...fields });
const auto = params.has("auto") ? [
  make("auto-accepted", { curationStatus: "accepted", curationStatusUpdatedBy: "auto:cyclotron", curationStatusUpdatedAt: ago(0.1), curationStatusReason: "Accepted automatically by the Cyclotron: it was 96.0% sure." }),
  make("rule-accepted", { curationStatus: "accepted", curationStatusUpdatedBy: "auto:rule", curationStatusUpdatedAt: ago(0.15), curationStatusReason: "Accepted automatically by the ttab monitor's rule." }),
  make("editor-accepted", { curationStatus: "accepted", curationStatusUpdatedBy: "editor@example.test", curationStatusUpdatedAt: ago(0.2) }),
] : [];
const FIXTURE = [
  ...auto,
  make("strong-accept"), make("mid-accept"), make("no-prediction"), make("weak-reject"), make("broken-image"), make("strong-reject"),
  ...(params.has("aged") ? [make("aged-out", { createdAt: ago(400), sourcePublishedAt: ago(400) })] : []),
];
const DECISIONS = new Map([["strong-accept", decision("include", 0.96)], ["mid-accept", decision("include", 0.7)], ["weak-reject", decision("exclude", 0.62)],
  ["broken-image", decision("include", 0.8)], ["strong-reject", decision("exclude", 0.94)], ["aged-out", decision("include", 0.9)]]);
const previews = new Map(FIXTURE.map((item) => [item.lineageId, { imageUrl: item.lineageId === "broken-image" ? "https://images.example.org/missing.png" : "https://images.example.org/ok.svg", description: "A one line dek for " + item.lineageId + ".", siteName: item.lineageId.replace(/-/g, " "), title: null }]));
previews.delete("no-prediction");
previews.set("mid-accept", { ...previews.get("mid-accept"), imageUrl: "https://opengraph.githubassets.com/abc/owner/repo" });
window.calls = [];
let tick = 0;

function Harness() {
  const [references, setReferences] = useState(FIXTURE);
  const [visitRated, setVisitRated] = useState(new Set());
  const { sort, setSort, show, setShow } = useFeedPreferences();
  const live = useMemo(() => buildFeedItems(references, DECISIONS), [references]);
  // The same rule as the page: the order is taken once and left alone.
  const snapshot = useRef(null);
  if (!snapshot.current) snapshot.current = takeFeedOrderSnapshot(live);
  const stable = applyFeedOrderSnapshot(snapshot.current, live, sort, show);
  return <ReferenceFeed
    loading={params.has("loading")}
    now={NOW}
    onOpen={(id) => window.calls.push({ type: "open", id })}
    onRate={async (reference, choice, reasonCode) => {
      window.calls.push({ type: "rate", id: reference.lineageId, choice, reasonCode });
      if (params.has("fail")) throw new Error("The backend refused this.");
      setReferences((current) => current.map((item) => item.lineageId === reference.lineageId
        ? { ...item, curationStatus: choice === "accept" ? "accepted" : "rejected", curationStatusUpdatedAt: new Date(NOW + (tick += 1) * 1000).toISOString() } : item));
    }}
    onShowChange={setShow}
    onSortChange={setSort}
    onVisitRated={(id) => setVisitRated((current) => new Set(current).add(id))}
    items={stable.items}
    leadId={stable.leadId}
    ratedCount={live.filter((item) => item.rated).length}
    previews={previews}
    show={show}
    sort={sort}
    visitRated={visitRated}
    disabledReason={params.get("disabled")}
  />;
}

// A newsroom with far more relations than any page budget: 60 References, 20000 relation records, and the one read the page makes per Reference.
window.reads = [];
window.noiseRelations = 20000;
function PagedHarness() {
  const total = Number(params.get("total") || 60);
  const references = useMemo(() => Array.from({ length: total }, (_, index) => make("p" + index, { createdAt: ago(0.001 * (index + 1)), sourcePublishedAt: ago(0.4 + 0.001 * index) })), [total]);
  const [relations, setRelations] = useState([]);
  const failed = useRef(new Set());
  const load = async (lineageId) => {
    window.reads.push(lineageId);
    await new Promise((resolve) => setTimeout(resolve, 5));
    if (params.has("failAll") || (params.get("failOne") === lineageId && !failed.current.has(lineageId))) {
      failed.current.add(lineageId);
      throw new Error("The relation index refused " + lineageId + ".");
    }
    const index = Number(lineageId.slice(1));
    return [
      { id: "noise-" + lineageId, predicate: "classified_as", relationState: "current", subjectKind: "reference", subjectLineageId: lineageId },
      { id: "rel-" + lineageId, predicate: "relevance_decision_is", relationState: "current", subjectKind: "reference", subjectLineageId: lineageId,
        confidence: 0.5 + ((index * 7) % 45) / 100, metadata: { label: index % 5 === 4 ? "exclude" : "include", decisionId: "d" + index, positiveLabel: "include", labels: ["include", "exclude"], reviewControl: "thumbs" } },
    ];
  };
  const [requested, setRequested] = useState([]);
  const request = useCallback((ids) => setRequested((current) => (ids.every((id) => current.includes(id)) ? current : [...new Set([...current, ...ids])])), []);
  const predictions = useReferencePredictions({
    enabled: true, ids: requested, load,
    onRelations: (lineageId, rows) => setRelations((current) => [...current.filter((row) => row.subjectLineageId !== lineageId), ...rows]),
  });
  const decisions = useMemo(() => currentRelevanceDecisions(relations), [relations]);
  const { sort, setSort, show, setShow } = useFeedPreferences();
  const all = useMemo(() => buildFeedItems(references, decisions), [references, decisions]);
  const windowState = useFeedWindow({ allItems: all, blocked: false, predictionStatuses: predictions.statuses, onRequestPredictions: request, sort, show, visitRated: new Set() });
  return <ReferenceFeed
    now={NOW}
    onOpen={() => undefined}
    onRate={async () => undefined}
    onShowChange={setShow}
    onSortChange={setSort}
    onVisitRated={() => undefined}
    items={windowState.items}
    leadId={windowState.leadId}
    ratedCount={0}
    previews={new Map()}
    show={show}
    sort={sort}
    visitRated={new Set()}
    predictionStatuses={predictions.statuses}
    onRetryPrediction={predictions.retry}
    hasMore={windowState.hasMore}
    loadingMore={windowState.loadingMore}
    onLoadMore={windowState.loadMore}
  />;
}

// A synthetic site read through the feed-state indexes: three corpora (one holds almost everything), thousands of References, and a
// fake backend that records every request. Nothing here can read a whole table, so the log shows exactly what the page asks for.
window.requests = [];
function buildSite(total) {
  const rows = [];
  for (let i = 0; i < total; i += 1) {
    const corpusId = i % 100 < 93 ? "knowledge-corpus-research" : i % 100 < 98 ? "knowledge-corpus-journalism" : "knowledge-corpus-history";
    const arrival = new Date(NOW - i * 60000).toISOString();
    const probability = ((i * 37) % 100) / 100;
    const rated = i % 10 === 9;
    const source = ["monitor", "manual", "email"][i % 3];
    rows.push({ id: "s" + i + "-v1", lineageId: "s" + i, versionState: "current", versionNumber: 1, corpusId, externalItemId: "s" + i, title: "Title of s" + i,
      sourceUri: "https://s" + i + ".example.org/story", curationStatus: rated ? "accepted" : "pending", createdAt: arrival, feedArrivalAt: arrival,
      feedStateKey: corpusId + (rated ? "#rated" : "#unrated"), predictedAcceptProbability: probability,
      predictionSortKey: predictionSortKeyFor(probability, arrival, "s" + i + "-v1"), versionCreatedBy: source === "manual" ? "editor" : source === "email" ? "email-submission" : "papyrus-monitoring-worker",
      discoveredByMonitorId: source === "monitor" ? "monitor-" + (i % 7) : null });
  }
  return rows;
}
const SITE_TOTAL = Number(params.get("total") || 7000);
const SITE = buildSite(SITE_TOTAL);
window.site = SITE;
const partitionCache = new Map();
function partition(key, sort) {
  const cacheKey = key + "|" + sort;
  if (!partitionCache.has(cacheKey)) partitionCache.set(cacheKey, SITE.filter((row) => row.feedStateKey === key).sort(compareFeedRecords(sort)));
  return partitionCache.get(cacheKey);
}
let failuresLeft = Number(params.get("failFirst") || 0);
const source = {
  loadCorpusIds: async () => { window.requests.push({ kind: "corpora" }); return ["knowledge-corpus-research", "knowledge-corpus-journalism", "knowledge-corpus-history"]; },
  readStream: async ({ feedStateKey, sort, limit, nextToken }) => {
    window.requests.push({ kind: "index", key: feedStateKey, sort, limit, token: nextToken });
    await new Promise((resolve) => setTimeout(resolve, Number(params.get("slow") || 5)));
    if (failuresLeft > 0) { failuresLeft -= 1; throw new Error("The index read was refused."); }
    if (params.has("empty")) return { items: [], nextToken: null };
    const rows = partition(feedStateKey, sort);
    const start = nextToken ? Number(nextToken) : 0;
    const items = rows.slice(start, start + limit);
    return { items, nextToken: start + items.length < rows.length ? String(start + items.length) : null };
  },
};
function IndexedHarness() {
  const { sort, setSort, show, setShow } = useFeedPreferences();
  const feed = useIndexedReferenceFeed({ enabled: true, source, sort, show });
  const items = useMemo(() => feed.records.map((record) => ({ ...scoreFeedItem(record, undefined), probability: record.predictedAcceptProbability ?? 0.5 })), [feed.records]);
  // The page's own per-card work: attachments for the cards shown, one batch for the ids not asked about yet.
  const asked = useRef(new Set());
  useEffect(() => {
    const fresh = feed.records.map((record) => record.lineageId).filter((id) => !asked.current.has(id));
    if (!fresh.length) return;
    fresh.forEach((id) => asked.current.add(id));
    window.requests.push({ kind: "attachments", ids: fresh });
  }, [feed.records]);
  return <ReferenceFeed
    error={feed.error ?? feed.moreError}
    hasMore={feed.hasMore}
    items={items}
    leadId={feedLeadId(items)}
    loading={feed.status === "loading" || feed.status === "idle"}
    loadingMore={feed.loadingMore}
    now={NOW}
    onLoadMore={() => { void feed.loadMore(); }}
    onOpen={() => undefined}
    onRate={async () => undefined}
    onRetry={feed.retry}
    onShowChange={setShow}
    onSortChange={setSort}
    onVisitRated={() => undefined}
    previews={new Map()}
    ratedCount={params.has("empty") ? 0 : 1}
    show={show}
    sort={sort}
    visitRated={new Set()}
  />;
}

// The References page search box: a synthetic site of rated (accepted, rejected) and unrated References, searched by the same matcher the local preview
// uses, standing in for the site's searchReferences query. The reader records every search it is asked for.
window.searches = [];
function buildSearchSite() {
  const row = (id, title, state, extra = {}) => ({ ...make(id, { title, curationStatus: state === "unrated" ? "pending" : state, ...extra }), feedStateKey: "c#" + (state === "unrated" ? "unrated" : "rated"), feedArrivalAt: ago(0.3 + 0.001 * (made += 1)) });
  return [
    row("rejected-by-author", "Notes on tool use in practice", "rejected", { authors: ["Marta Okafor"] }),
    row("unrated-by-title", "Persistent notebooks for agents", "unrated"),
    row("accepted-meaning", "Recall in long-running assistants", "accepted"),
    row("both", "Memory and recall in agent loops", "unrated"),
    row("chips-history", "A history of memory chips", "accepted"),
    ...Array.from({ length: 40 }, (_, index) => row("shared-" + index, "Shared topic number " + index, index % 3 === 0 ? "unrated" : index % 3 === 1 ? "accepted" : "rejected")),
  ];
}
const SEARCH_SITE = buildSearchSite();
const SEARCH_MEANING = { memory: ["recall"] };
const searchLanes = () => params.get("lane") === "meaning-down" ? { keyword: { status: "ok" }, meaning: { status: "failed", message: "Meaning search could not be reached." } }
  : params.get("lane") === "both-down" ? { keyword: { status: "failed" }, meaning: { status: "failed" } } : undefined;
let laneFailuresLeft = Number(params.get("laneOnce") || 0);
const searchReader = async (input) => {
  window.searches.push({ query: input.query, show: input.show, limit: input.limit, cursor: input.cursor });
  await new Promise((resolve) => setTimeout(resolve, 5));
  if (laneFailuresLeft > 0) { laneFailuresLeft -= 1; return previewSearch(SEARCH_SITE, input, { meaning: SEARCH_MEANING, lanes: { keyword: { status: "ok" }, meaning: { status: "failed" } } }); }
  return previewSearch(SEARCH_SITE, input, { meaning: SEARCH_MEANING, lanes: searchLanes() });
};
function SearchHarness() {
  const controls = useFeedControls({ searchRead: searchReader });
  const { search } = controls;
  const [answers, setAnswers] = useState({});
  const items = useMemo(() => search.feed.records.map((record) => scoreFeedItem({ ...record, curationStatus: answers[record.lineageId] ?? record.curationStatus }, undefined)), [search.feed.records, answers]);
  return <ReferenceFeed
    error={search.feed.error ?? search.feed.moreError}
    hasMore={search.feed.hasMore}
    items={items}
    leadId={search.searching ? undefined : feedLeadId(items)}
    loading={search.searching && (search.feed.status === "loading" || search.feed.status === "idle")}
    loadingMore={search.feed.loadingMore}
    now={NOW}
    onLoadMore={() => { void search.feed.loadMore(); }}
    onOpen={() => undefined}
    onRate={async (reference, choice) => { window.calls.push({ type: "rate", id: reference.lineageId, choice }); setAnswers((current) => ({ ...current, [reference.lineageId]: choice === "accept" ? "accepted" : "rejected" })); }}
    onRetry={search.feed.retry}
    onShowChange={controls.setShow}
    onSortChange={controls.setSort}
    onVisitRated={() => undefined}
    previews={new Map()}
    ratedCount={1}
    search={{ query: search.query, onSubmit: search.submit, onClear: search.clear, matches: search.feed.matches, notice: search.feed.notice, onRetry: search.feed.retry }}
    show={controls.show}
    sort={controls.sort}
    visitRated={new Set()}
  />;
}

// The Quality sort and the minimum of stars: a synthetic site read through the same hooks the page uses (the feed-state index, the star
// partitions, and the search), in memory like the local preview. Archived and superseded References keep their star key, as the real index does.
function buildQualitySite() {
  const day = (days) => new Date(NOW - days * DAY).toISOString();
  const row = (id, stars, state, days, extra = {}) => ({ ...make(id, { title: "Quality topic " + id, curationStatus: state === "unrated" ? "pending" : state, createdAt: day(days), sourcePublishedAt: day(days), ...(stars ? { starRating: stars } : {}), ...extra }) });
  let rows = [
    row("five-new", 5, "accepted", 1, { captureState: "none" }), row("five-old", 5, "unrated", 6, { captureState: "full" }), row("four-new", 4, "rejected", 2, { corpusId: "d", captureState: "thin" }), row("four-old", 4, "unrated", 7),
    row("three", 3, "accepted", 3, { captureState: "full" }), row("two", 2, "accepted", 4, { corpusId: "d", captureState: "running" }), row("one", 1, "unrated", 5, { captureState: "none" }),
    row("plain-new", 0, "unrated", 0.5, { captureState: "full" }), row("plain-old", 0, "unrated", 8, { captureState: "none" }),
    row("archived-five", 5, "archived", 0.2), row("superseded-four", 4, "unrated", 0.3, { versionState: "superseded" }),
  ];
  if (params.has("videos")) {
    // Videos among the rest: two waiting, one accepted, one rejected, one in another corpus, a starred one, and an article with no medium (not in the medium index).
    rows.push(
      row("video-new", 0, "unrated", 0.2, { medium: "video", sourceUri: "https://www.youtube.com/watch?v=aaaaaaaaaaa" }),
      row("video-old", 0, "unrated", 9, { medium: "video" }),
      row("video-accepted", 0, "accepted", 1.5, { medium: "video" }),
      row("video-rejected", 0, "rejected", 2.5, { medium: "video" }),
      row("video-other-corpus", 0, "unrated", 0.6, { medium: "video", corpusId: "d" }),
      row("video-starred", 4, "accepted", 3.5, { medium: "video" }),
      row("video-archived", 0, "archived", 0.1, { medium: "video" }),
    );
  }
  rows = rows.filter((reference) => !(params.has("noFive") && reference.starRating === 5 && reference.curationStatus !== "archived"));
  if (params.has("filtered")) {
    // Sixty newer References we hold in full, ahead of three we could not collect: Captured No filters whole pages away before the first match.
    for (let index = 0; index < 60; index += 1) rows.push(row("held-" + index, 0, "unrated", 0.001 * (index + 1), { captureState: "full" }));
    for (let index = 0; index < 3; index += 1) rows.push(row("tail-" + index, 0, "unrated", 20 + index, { captureState: "none" }));
  }
  if (params.has("ghosts")) {
    for (let index = 0; index < 60; index += 1) rows.push(row("ghost-" + index, 5, "archived", 0.001 * (index + 1)));
  }
  return rows;
}
const QUALITY_SITE = buildQualitySite();
const qualityFeedRead = feedReaderFromRecords(QUALITY_SITE);
const qualityStarRead = starReaderFromRecords(QUALITY_SITE);
const qualityMediumRead = mediumReaderFromRecords(QUALITY_SITE);
const qualitySource = {
  loadCorpusIds: async () => ["c", "d"],
  readStream: async (query) => { window.requests.push({ kind: "index", key: query.feedStateKey, sort: query.sort, limit: query.limit }); return qualityFeedRead(query); },
  readStarStream: async (query) => { window.requests.push({ kind: "stars", key: query.feedStateKey, sort: query.sort, limit: query.limit }); return qualityStarRead(query); },
  readMediumStream: async (query) => { window.requests.push({ kind: "medium", key: query.feedStateKey, sort: query.sort, limit: query.limit }); return qualityMediumRead(query); },
};
const qualitySearch = async (input) => {
  window.searches.push({ query: input.query, show: input.show, limit: input.limit, cursor: input.cursor, sort: input.sort, minStars: input.minStars, captured: input.captured });
  return previewSearch(QUALITY_SITE, input);
};
function QualityHarness() {
  const controls = useFeedControls({ searchRead: qualitySearch });
  const { search, minStars, captured } = controls;
  const feed = useIndexedReferenceFeed({ enabled: !search.searching, source: qualitySource, sort: controls.saved.sort, show: controls.saved.show, minStars, captured, medium: controls.medium });
  const active = search.searching ? search.feed : feed;
  const items = useMemo(() => active.records.map((record) => scoreFeedItem(record, undefined)), [active.records]);
  return <ReferenceFeed
    error={active.error ?? active.moreError}
    hasMore={active.hasMore}
    items={items}
    leadId={undefined}
    loading={active.status === "loading" || active.status === "idle"}
    loadingMore={active.loadingMore}
    captured={captured}
    medium={controls.medium}
    minStars={minStars}
    now={NOW}
    onMediumChange={controls.setMedium}
    onCapturedChange={controls.setCaptured}
    onLoadMore={() => { void active.loadMore(); }}
    onMinStarsChange={controls.setMinStars}
    onOpen={() => undefined}
    onRate={async () => undefined}
    onRetry={active.retry}
    onShowChange={controls.setShow}
    onSortChange={controls.setSort}
    onVisitRated={() => undefined}
    previews={new Map()}
    ratedCount={1}
    search={{ query: search.query, onSubmit: search.submit, onClear: search.clear, matches: search.feed.matches, notice: search.feed.notice, onRetry: search.feed.retry }}
    show={controls.show}
    sort={controls.sort}
    visitRated={new Set()}
  />;
}
createRoot(document.getElementById("root")).render(params.has("quality") ? <QualityHarness /> : params.has("search") ? <SearchHarness /> : params.has("indexed") ? <IndexedHarness /> : params.has("page-loading") ? <ReferencesPageLoading /> : params.has("paged") ? <PagedHarness /> : <Harness />);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#6a8"/></svg>';
const fixtureCss = "body{margin:0;font:16px sans-serif}button,textarea{font:inherit}";

async function setup(options = "", width = 1440, beforeLoad?: (page: Page) => Promise<void>) {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  page.setDefaultTimeout(4000);
  const errors: string[] = [];
  const requests: Array<{ url: string; referrer: string | undefined }> = [];
  page.on("pageerror", (error) => { errors.push(error.message); if (process.env.FEED_DEBUG) console.log(`[page error] ${error.message}`); });
  if (process.env.FEED_DEBUG) page.on("console", (message) => console.log(`[browser ${message.type()}] ${message.text()}`));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === "https://opengraph.githubassets.com") {
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640"><rect width="1280" height="640" fill="#fff"/></svg>' });
    }
    if (url.origin === "https://images.example.org") {
      requests.push({ url: url.href, referrer: route.request().headers().referer });
      return url.pathname.endsWith("ok.svg") ? route.fulfill({ contentType: "image/svg+xml", body: SVG }) : route.fulfill({ status: 404, body: "" });
    }
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/api/newsroom/source-icon") {
      requests.push({ url: url.href, referrer: route.request().headers().referer });
      return url.searchParams.get("host")?.includes("broken") ? route.fulfill({ status: 404, body: "" }) : route.fulfill({ contentType: "image/svg+xml", body: SVG });
    }
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript; charset=utf-8", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${tailwind}</style><style>${fixtureCss}</style></head><body><div id="root" class="p-4"></div><script src="/fixture.js"></script></body></html>` });
  });
  if (beforeLoad) await beforeLoad(page);
  await page.goto(`${origin}/${options}`);
  return { browser, page, errors, requests };
}

async function run(options: string, widths: number[], body: (page: Page, width: number, extra: { requests: Array<{ url: string; referrer: string | undefined }> }) => Promise<void>, beforeLoad?: (page: Page) => Promise<void>) {
  for (const width of widths) {
    const { browser, page, errors, requests } = await setup(options, width, beforeLoad);
    try {
      await body(page, width, { requests });
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  }
}

const cards = (page: Page) => page.locator("[data-feed-card]");
const order = (page: Page) => cards(page).evaluateAll((elements) => elements.map((element) => element.getAttribute("data-feed-card")));
const card = (page: Page, id: string) => page.locator(`[data-feed-card="${id}"]`);

const shots = process.env.FEED_SHOTS;
const scenarios: Record<string, () => Promise<void>> = {
  /** A responsive grid, a larger lead card, and the strongest Accepts first and the strongest Rejects last. */
  async layout() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      assert.deepEqual(await order(page), ["strong-accept", "broken-image", "mid-accept", "no-prediction", "weak-reject", "strong-reject"]);
      const columns = await page.locator("[data-feed-grid]").first().evaluate((grid) => getComputedStyle(grid).gridTemplateColumns.split(" ").length);
      const lead = (await card(page, "strong-accept").boundingBox())!;
      const second = (await card(page, "mid-accept").boundingBox())!;
      if (width === 375) {
        assert.equal(columns, 1, "one column on a phone");
        assert.ok(Math.abs(lead.width - second.width) < 2);
      } else {
        assert.ok(columns >= 3, "three or more columns on a desktop, got " + columns);
        assert.ok(lead.width > second.width * 1.5, "the lead card is larger than the others");
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
      const first = card(page, "strong-accept");
      assert.ok((await first.innerText()).includes("Title of strong-accept"), "the title");
      assert.ok((await first.innerText()).includes("A one line dek for strong-accept."), "the one-line dek");
      assert.ok((await first.locator("[data-feed-source]").innerText()).includes("strong accept"), "the source name");
      assert.ok((await first.locator("time").innerText()).length > 0, "its age");
      // The prediction: its side marked on the button, its confidence in the bar.
      const marked = first.locator("[data-review-choice][data-predicted]");
      assert.equal((await marked.innerText()).replace(/\s+/g, " ").trim().toLowerCase(), "accept predicted");
      assert.ok((await marked.locator("svg").count()) >= 1, "a Lucide icon, never colour alone");
      assert.equal(await first.locator("[data-confidence-value]").innerText(), "96%", "the confidence is in the bar");
      assert.equal((await card(page, "strong-reject").locator("[data-review-choice][data-predicted]").innerText()).replace(/\s+/g, " ").trim().toLowerCase(), "reject predicted");
      assert.equal(await card(page, "strong-reject").locator("[data-confidence-value]").innerText(), "94%");
      assert.match(await card(page, "no-prediction").locator("[data-prediction-caption]").innerText(), /^no prediction$/i);
      for (const choice of ["accept", "reject"]) {
        const box = (await first.locator(`[data-review-choice=${choice}]`).boundingBox())!;
        assert.ok(box.height >= 36 && box.width >= 60, `a tap-sized ${choice} button`);
      }
      assert.equal(await page.locator("select").count(), 0, "no drop-downs");
      assert.equal(await page.locator("[role=tab], [role=tablist]").count(), 0, "no tabs");
    });
  },

  /** Flat surfaces: no borders, outlines, rules or boxes anywhere in the feed; rounded cards and pills; sections with real headings. */
  async design() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      await page.locator("[data-feed-sort-button=newest]").hover();
      const offenders = await page.locator("[data-reference-feed], [data-reference-feed] *").evaluateAll((elements) => elements.flatMap((element) => {
        const style = getComputedStyle(element);
        const edges = ["Top", "Right", "Bottom", "Left"].some((edge) => parseFloat(style.getPropertyValue(`border-${edge.toLowerCase()}-width`)) > 0 && style.getPropertyValue(`border-${edge.toLowerCase()}-style`) !== "none");
        const outline = style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
        return edges || outline || element.tagName === "HR" ? [element.tagName + "." + String(element.getAttribute("class")).slice(0, 60)] : [];
      }));
      assert.deepEqual(offenders, [], "no border, outline or rule");
      const radius = (selector: string) => page.locator(selector).first().evaluate((element) => parseFloat(getComputedStyle(element).borderTopLeftRadius));
      assert.ok((await radius("[data-feed-card]")) >= 8, "cards are about 8 to 10px round (the --feed-radius tokens)");
      assert.ok((await radius("[data-review-choice=accept]")) >= 6, "buttons are rounded rectangles");
      assert.ok((await radius("[data-review-choice][data-predicted]")) >= 6);
      assert.ok((await radius("[data-confidence-bar]")) >= 4);
      assert.ok((await radius("[data-feed-sort-button=best]")) >= 6);
      // The image is full-bleed across the top of the card: as wide as the card, starting at its top edge.
      const box = (await card(page, "mid-accept").boundingBox())!;
      const image = (await card(page, "mid-accept").locator("[data-feed-image]").boundingBox())!;
      assert.ok(Math.abs(image.width - box.width) < 1 && Math.abs(image.y - box.y) < 1, "full-bleed top image");
      // One list in rank order, with no section headings: the predicted Rejects simply come last.
      assert.equal(await page.locator("[data-feed-group]").count(), 0, "no sections");
      const feedText = await page.locator("[data-reference-feed]").innerText();
      for (const heading of ["Top predictions", "More for you", "Least likely"]) assert.ok(!feedText.includes(heading), `no "${heading}" heading`);
      const ranked = await page.locator("[data-feed-grid]").first().locator("[data-feed-card]").evaluateAll((elements) => elements.map((element) => element.getAttribute("data-feed-card")));
      assert.deepEqual(ranked.slice(-2), ["weak-reject", "strong-reject"], "the predicted Rejects are last in the one list");
      // Phone: the first card is on the first screen.
      if (width === 375) assert.ok((await card(page, "strong-accept").locator("[data-feed-image]").boundingBox())!.y < 500, "the first card's picture is on the first screen");
      // A card that adds nothing to its headline drops its dek.
      assert.equal(await card(page, "strong-accept").locator("[data-feed-dek]").count(), 1);
    });
  },

  /** One control: the prediction bar, the two buttons and the reason field share one column, and the predicted side is marked on the button itself. */
  async grid() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const box = async (selector: string) => (await page.locator(selector).first().boundingBox())!;
      for (const id of ["strong-accept", "strong-reject", "no-prediction"]) {
        const base = `[data-feed-card="${id}"]`;
        const row = await box(`${base} [data-review-row=you]`);
        // One column: the bar, the pair of buttons and the reason field start and end together.
        for (const [name, part] of [["the bar", await box(`${base} [data-confidence-bar]`)], ["the reason field", await box(`${base} [data-review-reason] textarea`)]] as const) {
          assert.ok(Math.abs(part.x - row.x) < 0.5 && Math.abs(part.width - row.width) < 0.5, `${id}: ${name} is the same width as the buttons`);
        }
        const accept = await box(`${base} [data-review-choice=accept]`);
        const reject = await box(`${base} [data-review-choice=reject]`);
        assert.ok(accept.x < reject.x && accept.y === reject.y, "Accept is the left button, Reject the right, on one row");
        assert.ok(Math.abs(accept.width - reject.width) < 0.5, `${id}: the two buttons are the same width`);
      }
      // There is no second row of prediction cells: the prediction lives on the button and in the bar.
      assert.equal(await page.locator("[data-review-row=cyclotron], [data-cyclotron-choice]").count(), 0, "no prediction row");
      const predicted = card(page, "strong-accept").locator("[data-review-choice][data-predicted]");
      assert.equal(await predicted.getAttribute("data-review-choice"), "accept", "the predicted side is marked on the button");
      assert.equal(await predicted.getAttribute("data-state"), "predicted");
      assert.ok(/predicted/i.test(await predicted.innerText()), "and says so in words (the label is uppercased in CSS)");
      assert.equal(await card(page, "strong-accept").locator("[data-review-choice=reject][data-predicted]").count(), 0);
      const fill = async (id: string) => page.locator(`[data-feed-card="${id}"] [data-confidence-fill]`).evaluate((el) => {
        const bar = el.parentElement!.getBoundingClientRect(); const rect = el.getBoundingClientRect();
        return { centre: bar.x + bar.width / 2, left: rect.x, right: rect.x + rect.width, share: rect.width / bar.width };
      });
      const lean = await fill("strong-accept");
      assert.ok(lean.right <= lean.centre + 1 && lean.left < lean.centre, "an Accept-leaning bar fills from the centre toward Accept (left)");
      assert.ok(Math.abs(lean.share - 0.46) < 0.02, "its length is |P - 0.5| x 2 of half the bar: 0.96 gives 46%");
      const against = await fill("strong-reject");
      assert.ok(against.left >= against.centre - 1 && against.right > against.centre, "a Reject-leaning bar fills from the centre toward Reject (right)");
      assert.ok(Math.abs(against.share - 0.44) < 0.02, "0.06 gives 44%");
      assert.equal(await page.locator('[data-feed-card="no-prediction"] [data-confidence-fill]').count(), 0, "no prediction: an empty bar");
      assert.equal(await page.locator('[data-feed-card="no-prediction"] [data-confidence-bar]').getAttribute("data-confidence-direction"), "none");
      assert.match(await card(page, "no-prediction").locator("[data-prediction-caption]").innerText(), /^no prediction$/i, "and says so above the empty bar");
      // The confidence is printed in the bar and on no button.
      assert.equal(await card(page, "strong-accept").locator("[data-confidence-fill] [data-confidence-value]").innerText(), "96%");
      for (const choice of ["accept", "reject"]) {
        assert.ok(!/%/.test(await card(page, "strong-accept").locator(`[data-review-choice=${choice}]`).innerText()), `no percentage on the ${choice} button`);
      }
      // A fill too short to hold its number keeps the number beside it instead (0.62 the other way is a 12% fill).
      assert.equal(await card(page, "weak-reject").locator("[data-confidence-fill] [data-confidence-value]").count(), 0, "a narrow fill holds no number");
      assert.equal(await card(page, "weak-reject").locator("[data-confidence-bar] > [data-confidence-value]").innerText(), "62%", "the number sits beside the fill");
      assert.equal(await page.locator("[data-feed-card] [data-review-choice] [data-verdict]").count(), 0, "no verdict before an answer");
      // Nothing spills out of a button at any card width the feed uses, down to a narrow card.
      for (const width of [240, 280, 360]) {
        const spills = await page.locator('[data-feed-card="strong-accept"] [data-decision-control]').evaluate((control, cardWidth) => {
          (control as HTMLElement).style.width = `${cardWidth}px`;
          const found = ([...control.querySelectorAll("[data-review-choice]")] as HTMLElement[]).filter((cell) => [...cell.querySelectorAll("*")].some((child) => {
            const outer = cell.getBoundingClientRect(); const inner = child.getBoundingClientRect();
            return inner.left < outer.left - 0.5 || inner.right > outer.right + 0.5;
          })).map((cell) => cell.getAttribute("data-review-choice"));
          (control as HTMLElement).style.width = "";
          return found;
        }, width);
        assert.deepEqual(spills, [], `at a ${width}px control every icon and word fits inside its button`);
      }
    });
  },

  /** After an answer: the prediction's marker and the bar carry the verdict; the answer itself never changes colour. */
  async verdict() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const rgb = (selector: string, property: "backgroundColor" | "color") => page.locator(selector).first().evaluate((el, prop) => {
        const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
        const context = canvas.getContext("2d")!; context.fillStyle = "#000"; context.fillStyle = getComputedStyle(el)[prop as "color"]; context.fillRect(0, 0, 1, 1);
        const [r, g, b] = context.getImageData(0, 0, 1, 1).data; return { r, g, b };
      }, property);
      // A confirmation: answer with the predicted side.
      await card(page, "strong-accept").locator("[data-review-choice=accept]").click();
      await card(page, "strong-accept").locator("[data-prediction-mark][data-verdict=match]").waitFor();
      assert.ok(/confirmed/i.test(await card(page, "strong-accept").locator("[data-review-choice=accept]").innerText()), "the answer says Confirmed");
      const markMatch = await rgb('[data-feed-card="strong-accept"] [data-prediction-mark][data-verdict=match]', "color");
      assert.ok(markMatch.g > markMatch.r && markMatch.g > markMatch.b, "the prediction's marker is green: " + JSON.stringify(markMatch));
      const barMatch = await rgb('[data-feed-card="strong-accept"] [data-confidence-fill]', "backgroundColor");
      assert.ok(barMatch.g > barMatch.r, "the bar turns green too: " + JSON.stringify(barMatch));
      // An overturn: answer Accept on a card predicted Reject.
      await card(page, "strong-reject").locator("[data-review-choice=accept]").click();
      await card(page, "strong-reject").locator("[data-prediction-mark][data-verdict=miss]").waitFor();
      assert.ok(/overturned/i.test(await card(page, "strong-reject").locator("[data-review-choice=accept]").innerText()), "the answer says Overturned");
      const markMiss = await rgb('[data-feed-card="strong-reject"] [data-prediction-mark][data-verdict=miss]', "color");
      assert.ok(markMiss.r > markMiss.g && markMiss.r > markMiss.b, "the marker is red: " + JSON.stringify(markMiss));
      const barMiss = await rgb('[data-feed-card="strong-reject"] [data-confidence-fill]', "backgroundColor");
      assert.ok(barMiss.r > barMiss.g, "the bar turns red too: " + JSON.stringify(barMiss));
      // The marker stays on the side the prediction picked, which is the losing side after an overturn.
      assert.equal(await card(page, "strong-reject").locator("[data-review-choice=reject][data-predicted] [data-prediction-mark]").count(), 1, "the marker stays on the predicted side");
      // The editor's own answer is never tinted by the verdict: the same fill confirms and overturns.
      const chosen = (id: string) => rgb(`[data-feed-card="${id}"] [data-review-choice=accept]`, "backgroundColor");
      assert.deepEqual(await chosen("strong-accept"), await chosen("strong-reject"), "a confirmed answer and an overturned one are the same colour");
      // Your chosen button is filled and the other quiet; tapping the chosen one never unselects it.
      const pressed = (id: string, choice: string) => card(page, id).locator(`[data-review-choice=${choice}]`).getAttribute("aria-pressed");
      assert.equal(await pressed("strong-accept", "accept"), "true");
      assert.equal(await pressed("strong-accept", "reject"), "false");
      await card(page, "strong-accept").locator("[data-review-choice=accept]").click();
      assert.equal(await pressed("strong-accept", "accept"), "true", "tapping the chosen answer does not unselect it");
      const classes = (choice: string) => card(page, "strong-accept").locator(`[data-review-choice=${choice}]`).getAttribute("class");
      assert.ok(/bg-\[var\(--primary\)\]/.test((await classes("accept")) ?? "") && /font-semibold/.test((await classes("accept")) ?? ""), "the chosen button is filled");
      assert.ok(!/bg-\[var\(--primary\)\]/.test((await classes("reject")) ?? ""), "the other is quiet");
    });
  },

  /** The image is lazy, has a fixed frame and no referrer; a missing image becomes a tile with the source name. */
  async images() {
    await run("", [375, 1440], async (page, _width, { requests }) => {
      await cards(page).first().waitFor();
      const image = card(page, "strong-accept").locator("[data-feed-image] img");
      await image.waitFor();
      assert.equal(await image.getAttribute("loading"), "lazy");
      assert.equal(await image.getAttribute("referrerpolicy"), "no-referrer");
      await page.waitForFunction(() => document.querySelector('[data-feed-card="strong-accept"] [data-feed-image]')?.getAttribute("data-feed-image-state") === "loaded");
      const frame = (await card(page, "strong-accept").locator("[data-feed-image]").boundingBox())!;
      assert.ok([1.6, 2, 21 / 9].some((ratio) => Math.abs(frame.width / frame.height - ratio) < 0.1), "the lead frame has a fixed ratio");
      const other = (await card(page, "weak-reject").locator("[data-feed-image]").boundingBox())!;
      assert.ok(Math.abs(other.width / other.height - 16 / 10) < 0.05, "other cards are 16:10");
      // A text card (a GitHub social card) is shown whole: its own ratio, contained, never cropped at the edges. Photos stay cover.
      const textCard = card(page, "mid-accept").locator("[data-feed-image]");
      await page.waitForFunction(() => document.querySelector('[data-feed-card="mid-accept"] [data-feed-image]')?.getAttribute("data-feed-image-state") === "loaded");
      assert.equal(await textCard.getAttribute("data-feed-image-fit"), "contain");
      assert.equal(await textCard.locator("img").evaluate((element) => getComputedStyle(element).objectFit), "contain");
      const cardBox = (await textCard.boundingBox())!;
      assert.ok(Math.abs(cardBox.width / cardBox.height - 2) < 0.05, "the frame takes the card's own 2:1 ratio");
      assert.equal(await card(page, "strong-accept").locator("[data-feed-image]").getAttribute("data-feed-image-fit"), "cover");
      await page.waitForFunction(() => document.querySelector('[data-feed-card="broken-image"] [data-feed-image-fallback]'));
      const fallback = card(page, "broken-image").locator("[data-feed-image-fallback]");
      assert.ok((await fallback.innerText()).includes("broken image"), "the tile names the source");
      assert.equal(await fallback.locator("svg").count(), 0, "no outline icon");
      assert.equal(await fallback.locator("[data-feed-source-mark]").count(), 1, "the source's mark, large and centred");
      assert.ok(/gradient/.test(await fallback.evaluate((element) => getComputedStyle(element).backgroundImage)), "a soft gradient from the source name");
      const noPreview = card(page, "no-prediction").locator("[data-feed-image-fallback]");
      assert.equal(await noPreview.count(), 1, "a Reference with no preview shows the tile at once");
      assert.ok(requests.every((request) => request.referrer === undefined || request.url.includes("/api/newsroom/source-icon")), "images are requested with no referrer");
      // Source icons come from the newsroom's own icon route, never a guessed /favicon.ico on the source; no icon means the letter.
      const marks = await page.locator("[data-feed-source-mark] img").evaluateAll((images) => images.map((image) => (image as HTMLImageElement).getAttribute("src") ?? ""));
      assert.ok(marks.length > 0 && marks.every((src) => src.startsWith("/api/newsroom/source-icon?host=")), "every source icon is asked of the newsroom");
      await page.waitForFunction(() => !document.querySelector('[data-feed-card="broken-image"] [data-feed-image-fallback] [data-feed-source-mark] img'));
      assert.match(await fallback.locator("[data-feed-source-mark]").innerText(), /^\S$/, "a source with no icon shows its first letter");
    });
  },

  /** A Reference the Cyclotron accepted on its own says so in words with an icon, and an editor's accept does not. */
  async auto() {
    await run("?auto", [375, 1440], async (page) => {
      await page.locator("[data-feed-show-button=all]").click();
      await card(page, "auto-accepted").waitFor();
      const badge = card(page, "auto-accepted").locator("[data-auto-accepted]");
      assert.equal(await badge.count(), 1, "the automatically accepted card carries the badge");
      assert.ok((await badge.innerText()).includes("Accepted automatically"), "in words");
      assert.equal(await badge.locator("svg").count(), 1, "with a Lucide icon");
      const byRule = card(page, "rule-accepted").locator("[data-auto-accepted=rule]");
      assert.equal(await byRule.count(), 1, "a rule monitor's delivery carries the badge too");
      assert.ok((await byRule.innerText()).includes("Accepted automatically (by rule)"), "and says it was by rule");
      assert.equal(await card(page, "editor-accepted").locator("[data-auto-accepted]").count(), 0, "an editor's accept is not marked");
      assert.equal(await card(page, "auto-accepted").getAttribute("data-feed-rated"), null, "an automatic acceptance is not the editor's answer yet: Accept confirms it, Reject overturns it");
    });
  },

  /** A rated card stays in place showing the answer, undo is the other choice, then it is hidden under Unrated on the next visit. */
  async lifecycle() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const before = await order(page);
      await card(page, "mid-accept").locator("[data-review-choice=accept]").click();
      await card(page, "mid-accept").locator("[data-prediction-mark][data-verdict=match]").waitFor();
      assert.deepEqual(await order(page), before, "the rated card stays in place");
      assert.equal(await card(page, "mid-accept").getAttribute("data-feed-rated"), "accept");
      assert.ok(/confirmed/i.test(await card(page, "mid-accept").locator("[data-review-choice=accept]").innerText()), "the answer says Confirmed");
      assert.equal(await card(page, "mid-accept").locator("[data-prediction-mark] svg").count(), 1, "with its marker, never colour alone");
      assert.ok((await card(page, "mid-accept").locator("[data-feed-saved]").innerText()).includes("Recorded"));
      assert.equal(await card(page, "mid-accept").locator("[data-review-choice=accept]").getAttribute("aria-pressed"), "true");

      // The other choice is the undo: Reject waits for a written reason, and nothing changes until one is given.
      await card(page, "mid-accept").locator("[data-review-choice=reject]").click();
      assert.equal(await card(page, "mid-accept").locator("[data-review-record]").count(), 1, "a reason is asked for in words");
      assert.ok((await card(page, "mid-accept").locator("[data-feed-saved]").innerText()).includes("A reason is needed"));
      assert.ok(/needs a reason/i.test(await card(page, "mid-accept").locator("[data-review-choice=reject]").innerText()), "the staged button says what is missing, not that it is unrecorded");
      assert.equal(await card(page, "mid-accept").getAttribute("data-feed-rated"), "accept", "nothing changes until a reason is written");
      await card(page, "mid-accept").locator("[data-review-reason] textarea").fill("The same study, already in the corpus.");
      await card(page, "mid-accept").locator("[data-review-record]").click();
      await card(page, "mid-accept").locator("[data-prediction-mark][data-verdict=miss]").waitFor();
      assert.ok(/overturned/i.test(await card(page, "mid-accept").locator("[data-review-choice=reject]").innerText()));
      assert.deepEqual(await order(page), before);
      const calls = await page.evaluate(() => (window as unknown as { calls: unknown[] }).calls);
      assert.deepEqual(calls, [
        { type: "rate", id: "mid-accept", choice: "accept", reasonCode: null },
        { type: "rate", id: "mid-accept", choice: "reject", reasonCode: null },
      ], "a written reason carries no code the editor did not pick: the backend reads the words for it");

      // A Reject that was predicted is a confirmation, and it also needs its reason in words.
      await card(page, "strong-reject").locator("[data-review-choice=reject]").click();
      assert.equal(await card(page, "strong-reject").locator("[data-review-record]").count(), 1);
      await card(page, "strong-reject").locator("[data-review-reason] textarea").fill("Out of scope for this desk.");
      await card(page, "strong-reject").locator("[data-review-record]").click();
      await card(page, "strong-reject").locator("[data-prediction-mark][data-verdict=match]").waitFor();

      assert.deepEqual(await order(page), before, "both answers stay where they were");
      await page.locator("[data-feed-show-button=all]").click();
      assert.deepEqual(await order(page), before, "All adds nothing here: they are already listed");
      await card(page, "weak-reject").locator("[data-review-choice=accept]").first().waitFor();
      await card(page, "strong-accept").locator("[data-feed-open]").click();
      assert.deepEqual((await page.evaluate(() => (window as unknown as { calls: Array<{ type: string; id: string }> }).calls)).at(-1), { type: "open", id: "strong-accept" }, "the card body opens the review");
    });
  },

  /** An old unrated item stays in the one list, placed by its original confidence, and can be rated in place. */
  async aged() {
    await run("?aged", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const feedOrder = await order(page);
      assert.deepEqual(feedOrder, ["strong-accept", "aged-out", "broken-image", "mid-accept", "no-prediction", "weak-reject", "strong-reject"], "a year-old 90% Accept still ranks by its original confidence");
      assert.equal(await page.locator("[data-feed-earlier]").count(), 0, "no separate section");
      assert.equal(await page.locator("[role=tab]").count(), 0, "no tabs");
      await page.locator("[data-feed-sort-button=newest]").click();
      assert.equal((await order(page)).at(-1), "aged-out", "and last by date");
      await card(page, "aged-out").locator("[data-review-choice=accept]").click();
      await card(page, "aged-out").locator("[data-verdict=match]").waitFor();
      assert.equal((await order(page)).at(-1), "aged-out", "rated in place, not moved or removed");
    });
  },

  /** Predictions by default, Newest by date; Unrated by default, All adds the answered cards; both choices are remembered. */
  async sorting() {
    await run("?auto", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const pressed = (kind: string, key: string) => page.locator(`[data-feed-${kind}-button=${key}]`).getAttribute("aria-pressed");
      assert.equal(await pressed("sort", "best"), "true", "Predictions is the default");
      assert.equal(await pressed("show", "unrated"), "true", "Reviewed No is the default");
      for (const kind of ["sort", "show"]) {
        for (const button of await page.locator(`[data-feed-${kind}-button]`).all()) {
          assert.ok((await button.locator("svg").count()) >= 1, "a Lucide icon beside the words");
          assert.ok((await button.innerText()).trim().length > 0, "and words");
        }
      }
      assert.equal(await page.locator("select").count(), 0, "no drop-downs");
      assert.equal(await page.locator("[role=tab]").count(), 0, "no tabs");
      assert.deepEqual(await order(page), ["strong-accept", "broken-image", "mid-accept", "no-prediction", "weak-reject", "strong-reject"], "by confidence, and only unrated cards");

      await page.locator("[data-feed-sort-button=newest]").click();
      assert.equal(await pressed("sort", "newest"), "true");
      assert.equal(await pressed("sort", "best"), "false");
      assert.deepEqual(await order(page), ["strong-accept", "mid-accept", "no-prediction", "weak-reject", "broken-image", "strong-reject"], "newest first, whatever the predictions say");

      await page.locator("[data-feed-show-button=all]").click();
      assert.equal(await pressed("show", "all"), "true");
      const all = await order(page);
      for (const id of ["auto-accepted", "rule-accepted", "editor-accepted"]) assert.ok(all.includes(id), `${id} is listed under All`);
      assert.equal(all.length, 9);
      assert.deepEqual(all.slice(0, 3), ["auto-accepted", "rule-accepted", "editor-accepted"], "rated cards sit in the active sort (these three arrived last)");
      assert.equal(await card(page, "editor-accepted").getAttribute("data-feed-rated"), "accept", "a rated card shows its recorded vote");

      await page.reload();
      await cards(page).first().waitFor();
      assert.equal(await pressed("sort", "newest"), "true", "the sort is remembered");
      assert.equal(await pressed("show", "all"), "true", "and so is Show");
      assert.equal((await order(page)).length, 9);
      await page.locator("[data-feed-show-button=rated]").click();
      assert.equal(await pressed("show", "rated"), "true");
      assert.equal(await pressed("show", "all"), "false");
      const rated = await order(page);
      assert.deepEqual(rated, ["auto-accepted", "rule-accepted", "editor-accepted"], "Rated lists the answered cards alone, newest first");
      assert.equal(await card(page, "editor-accepted").getAttribute("data-feed-rated"), "accept", "a rated card still shows its recorded vote");
      assert.equal(await page.locator("[data-feed-lead]").count(), 0, "and has no lead card");
      await page.locator("[data-feed-sort-button=best]").click();
      assert.equal((await order(page)).length, 3, "Predictions also works with rated cards");
      assert.equal(await page.locator("[data-feed-show-button=rated] svg").count(), 1, "a Lucide icon beside the words");
      await page.reload();
      await cards(page).first().waitFor();
      assert.equal(await pressed("show", "rated"), "true", "Rated is remembered too");
      await page.locator("[data-feed-show-button=unrated]").click();
      assert.equal((await order(page)).length, 6);
    });
  },

  /** The shell and card skeletons show at once, with no "checking" text. */
  async skeleton() {
    await run("?loading=1", [375, 1440], async (page) => {
      const skeleton = page.locator("[data-reference-feed-skeleton]");
      await skeleton.waitFor();
      assert.equal(await skeleton.getAttribute("role"), "status");
      assert.equal(await skeleton.getAttribute("aria-label"), "Loading references");
      assert.ok((await skeleton.locator(".animate-pulse").count()) > 10);
      assert.equal(await cards(page).count(), 0);
      assert.equal(await page.locator("[data-feed-sort-button]").count(), 3, "the feed's controls are already on the page");
      assert.equal(await page.locator("[data-feed-show-button]").count(), 4);
      assert.ok(!/checking|credentials/i.test(await page.locator("body").innerText()));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    });
  },

  /** A return visit paints the last saved cards at once, read only, with the reason in words. */
  async cached() {
    const snapshot = JSON.stringify({
      savedAt: Date.now(),
      references: [1, 2, 3].map((index) => ({ id: `saved-${index}-v1`, lineageId: `saved-${index}`, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: `saved-${index}`, title: `Saved title ${index}`, sourceUri: `https://saved${index}.example.org/a`, curationStatus: "pending", createdAt: new Date(Date.now() - 3_600_000 * index).toISOString() })),
      previews: [["saved-1", { imageUrl: "https://images.example.org/ok.svg", description: "Saved dek.", siteName: "Saved One", title: null }]],
      decisions: [],
    });
    await run("?page-loading=1", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      assert.equal(await cards(page).count(), 3);
      const text = await page.locator("body").innerText();
      assert.ok(text.includes("Saved title 1") && text.includes("Saved dek."));
      assert.ok(!/checking credentials|checking sign-in/i.test(text), "no checking screen in front of the cards");
      assert.ok(text.includes("Showing your last view while it updates"));
      assert.ok(text.includes("Confirming your sign-in. You can answer in a moment."), "the disabled controls say why");
      await card(page, "saved-1").locator("[data-review-choice=accept]").click({ force: true });
      assert.equal(await card(page, "saved-1").getAttribute("data-feed-rated"), null, "a saved copy never answers on its own");
      await card(page, "saved-1").locator("[data-feed-open]").click();
      assert.ok((await page.locator("[role=status]").allInnerTexts()).join(" ").includes("available in a moment"), "opening says what is happening");
    }, async (page) => {
      await page.addInitScript((value) => { try { localStorage.setItem("papyrus.references.feed.v1.papyrus", value); } catch { /* none */ } }, snapshot);
    });
    // With no saved copy the page shows skeleton cards, not an empty page.
    await run("?page-loading=1", [375], async (page) => {
      await page.locator("[data-reference-feed-skeleton]").waitFor();
      assert.equal(await page.getByRole("heading", { name: "References" }).count(), 1);
    });
  },

  /** The ranking is explained in plain words, with this site's learned numbers. */
  async popover() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const button = page.getByRole("button", { name: "How this feed is ranked" });
      await button.click();
      const panel = page.locator("[data-feed-ranking-panel]");
      const text = await panel.innerText();
      for (const expected of ["A feed run by algorithms you control", "Predictions", "Newest", "Reviewed", "Accepted", "Captured", "Any", "Your answers stay put", "Age does not change"]) {
        assert.ok(text.includes(expected), `the popover says: ${expected}`);
      }
      const box = (await panel.boundingBox())!;
      assert.ok(box.x >= 0 && box.x + box.width <= (await page.evaluate(() => window.innerWidth)), "inside the screen");
      await page.keyboard.press("Escape");
      assert.equal(await panel.count(), 0);
    });
  },

  /**
   * A newsroom with more relations than any page budget: the feed reads one prediction per visible Reference, a later page only when
   * scrolled to, a failure shows on its own card, and the cards render without predictions.
   */
  async predictions() {
    const shots = process.env.FEED_PREDICTION_SHOTS;
    if (shots) fs.mkdirSync(shots, { recursive: true });
    const reads = (page: Page) => page.evaluate(() => (window as unknown as { reads: string[] }).reads.slice());
    const bars = (page: Page) => page.locator("[data-feed-card] [data-confidence-value]").count();
    await run("?paged", [390, 1440], async (page, width) => {
      await page.locator("[data-feed-card]").first().waitFor();
      await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length === 24 && document.querySelectorAll("[data-prediction-state]").length === 0);
      assert.equal((await reads(page)).length, 24, "one read for each Reference on the first page, none for the other 36 and none for the relation feed");
      assert.equal(await cards(page).count(), 24);
      assert.equal(await page.getByText(/Predictions unavailable|activity feed is incomplete/i).count(), 0, "no page-wide failure");
      assert.equal(await page.locator("[data-prediction-state=loading], [data-prediction-state=error]").count(), 0);
      const firstPage = await order(page);
      await page.locator("[data-feed-more]").scrollIntoViewIfNeeded();
      await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length === 48);
      assert.equal((await reads(page)).length, 48, "scrolling to the end reads the next page's predictions and only those");
      assert.deepEqual((await order(page)).slice(0, 24), firstPage, "the first page does not move when the next one joins");
      assert.equal(await bars(page), 48, "every card on screen has its prediction");
      if (shots) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({ path: `${shots}/feed-with-predictions-${width}.png` });
      }
    });
    await run("?paged&total=30&failOne=p3", [390, 1440], async (page, width) => {
      await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length === 24 && document.querySelectorAll("[data-prediction-state=loading]").length === 0);
      const failing = card(page, "p3");
      assert.match(await failing.locator("[data-prediction-caption]").innerText(), /prediction unavailable/i);
      assert.ok((await failing.locator("[data-retry-prediction]").innerText()).includes("Retry"), "a retry on that card");
      assert.equal(await page.locator("[data-prediction-state=error]").count(), 1, "only that card failed");
      assert.equal(await page.getByText(/Predictions unavailable/i).count(), 0, "no page-wide failure");
      assert.equal(await page.locator("[role=alert]").count(), 0);
      if (shots) await page.screenshot({ path: `${shots}/feed-one-card-failed-${width}.png` });
      await failing.locator("[data-retry-prediction]").click();
      await failing.locator("[data-confidence-value], [data-confidence-fill]").first().waitFor();
      assert.equal(await page.locator("[data-prediction-state=error]").count(), 0, "the retry read it");
    });
    await run("?paged&total=30&failAll=1", [390, 1440], async (page, width) => {
      await page.locator("[data-prediction-state=error]").first().waitFor();
      await page.waitForFunction(() => document.querySelectorAll("[data-prediction-state=loading]").length === 0);
      assert.equal(await cards(page).count(), 24, "the References still render, with titles and Accept and Reject buttons");
      assert.ok((await card(page, "p0").innerText()).includes("Title of p0"));
      assert.equal(await card(page, "p0").locator("[data-review-choice=accept]").count(), 1);
      assert.equal(await page.locator("[data-feed-card] [data-prediction-state=error]").count(), 24);
      assert.equal(await page.getByText(/Predictions unavailable/i).count(), 0, "no page-wide failure");
      if (shots) await page.screenshot({ path: `${shots}/feed-without-predictions-${width}.png` });
    });
  },


  /** The first cards come from one round of indexed reads; scrolling reads the next page; per-card reads follow the cards shown. */
  async indexed() {
    await run("?indexed=1&total=7000", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      await page.waitForFunction(() => window.requests.some((request) => request.kind === "attachments"));
      const log = () => page.evaluate(() => window.requests);
      const first = await log();
      const kinds = (list: Array<{ kind: string }>) => list.reduce<Record<string, number>>((all, request) => ({ ...all, [request.kind]: (all[request.kind] ?? 0) + 1 }), {});
      // One corpora read, one index read per corpus partition (three corpora, unrated), one attachments batch: no table is walked.
      assert.deepEqual(kinds(first), { corpora: 1, index: 3, attachments: 1 }, "first paint requests: " + JSON.stringify(kinds(first)));
      assert.ok(first.filter((request) => request.kind === "index").every((request) => request.limit === 24), "one page of 24 per partition, never a limit of 13");
      assert.equal(await cards(page).count(), 24, "one page of cards");
      const attachments = first.find((request) => request.kind === "attachments") as unknown as { ids: string[] };
      assert.equal(attachments.ids.length, 24, "attachments for the 24 cards shown, not the 13,000 in the table");
      // Predictions across all three corpora, highest original P first, newest on ties: the top of the merged partitions.
      const shown = await order(page) as string[];
      const expected = await page.evaluate(() => window.site
        .filter((row: any) => row.feedStateKey.endsWith("#unrated"))
        .sort((left: any, right: any) => (left.predictionSortKey < right.predictionSortKey ? 1 : -1))
        .slice(0, 24).map((row: any) => row.lineageId));
      assert.deepEqual(shown, expected, "the first page is the top of the merged index order");
      // Nothing more is read while the editor does not scroll.
      await page.waitForTimeout(700);
      assert.deepEqual(kinds(await log()), kinds(first), "an unscrolled page makes no further requests");
      // Scrolling to the end reads the next page, and only that page's attachments.
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length >= 48);
      await page.waitForFunction(() => window.requests.filter((request) => request.kind === "attachments").length >= 2);
      const afterScroll = await log();
      const secondBatch = afterScroll.filter((request) => request.kind === "attachments")[1] as unknown as { ids: string[] };
      assert.equal(secondBatch.ids.length, 24, "attachments for the next 24 cards only");
      assert.equal(new Set([...attachments.ids, ...secondBatch.ids]).size, 48, "no card is read twice");
      const scrollReads = afterScroll.length - first.length;
      assert.ok(afterScroll.filter((request) => request.kind === "index").length - 3 <= 3, "one scroll reads at most one more round of pages");
      assert.equal(await cards(page).count(), 48);
      console.log(`indexed requests at ${width}px: first paint ${first.length} (${JSON.stringify(kinds(first))}), one scroll +${scrollReads} (${JSON.stringify(kinds(afterScroll.slice(first.length)))})`);
      if (shots) { await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({ path: `${shots}/indexed-feed-${width}.png` }); }
    });
  },

  /** A merged order across corpora, and the empty, slow and failed reads. */
  async indexedStates() {
    await run("?indexed=1&total=600", [375], async (page) => {
      await cards(page).first().waitFor();
      assert.equal(await cards(page).count(), 24);
      await page.locator("[data-feed-sort-button=newest]").click();
      await page.waitForFunction(() => window.requests.some((request) => request.kind === "index" && request.sort === "newest"));
      await page.waitForFunction(() => document.querySelector("[data-feed-grid]") && document.querySelector("[data-feed-card='s0']"));
      assert.equal((await order(page))![0], "s0", "Newest starts with the latest arrival");
    });
    await run("?indexed=1&empty=1", [375, 1440], async (page) => {
      await page.locator("[data-feed-empty]").waitFor();
      assert.equal(await page.locator(".animate-pulse").count(), 0, "an empty feed shows the empty message, not a skeleton");
    });
    await run("?indexed=1&empty=1", [375, 1440], async (page) => {
      await page.locator("[data-feed-empty]").waitFor();
      await page.evaluate(() => { window.requests.length = 0; });
      await page.locator("[data-feed-show-button=rated]").click();
      await page.waitForFunction(() => window.requests.some((request) => request.kind === "index"));
      await page.locator("[data-feed-empty]").waitFor();
      assert.match(await page.locator("[data-feed-empty]").innerText(), /Nothing reviewed yet/, "an empty Reviewed Yes says so in plain words");
      const keys = await page.evaluate(() => window.requests.filter((request) => request.kind === "index").map((request) => (request as unknown as { key: string }).key));
      assert.ok(keys.length > 0 && keys.every((key) => key.endsWith("#rated")), "Rated reads the rated partitions alone");
    });
    await run("?indexed=1&slow=900", [375], async (page) => {
      await page.waitForTimeout(300);
      assert.equal(await page.locator("[data-feed-empty]").count(), 0, "a slow read never looks like no items");
      assert.equal(await cards(page).count(), 0);
      assert.equal(await page.locator("[data-feed-error]").count(), 0);
      await cards(page).first().waitFor({ timeout: 4000 });
    });
    await run("?indexed=1&failFirst=1&total=600", [375, 1440], async (page, width) => {
      await page.locator("[data-feed-error]").waitFor();
      assert.match(await page.locator("[data-feed-error]").innerText(), /could not be loaded[\s\S]*refused/i);
      assert.equal(await cards(page).count(), 0);
      if (shots) await page.screenshot({ path: `${shots}/indexed-error-${width}.png` });
      await page.locator("[data-feed-retry]").click();
      await cards(page).first().waitFor();
      assert.equal(await page.locator("[data-feed-error]").count(), 0, "Retry reads the feed again");
    });
  },

  /** Screenshots for review (FEED_SHOTS=dir): the old wait (skeletons only), the indexed feed, and the error with Retry. */
  async screens() {
    if (!shots) return;
    await run("?indexed=1&slow=600000", [375, 1440], async (page, width) => {
      await page.locator("[data-reference-feed-skeleton]").waitFor();
      await page.screenshot({ path: `${shots}/before-skeleton-only-${width}.png` });
    });
    await run("?indexed=1&total=7000", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${shots}/after-first-cards-${width}.png` });
    });
    await run("?indexed=1&failFirst=1", [375, 1440], async (page, width) => {
      await page.locator("[data-feed-error]").waitFor();
      await page.screenshot({ path: `${shots}/after-error-retry-${width}.png` });
    });
  },

  /** A Reference from a manual Add, from email and from a monitor appear in one feed, in order, with no difference by source. */
  async sources() {
    await run("?indexed=1&total=300", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      await page.locator("[data-feed-sort-button=newest]").click();
      await page.waitForFunction(() => document.querySelector("[data-feed-card='s0']") && document.querySelector("[data-feed-card='s1']") && document.querySelector("[data-feed-card='s2']"));
      const ids = (await order(page)) as string[];
      // s0 monitor, s1 manual Add, s2 email: consecutive arrivals, newest first, all in the one list.
      assert.deepEqual(ids.slice(0, 3), ["s0", "s1", "s2"]);
      const texts = await Promise.all(["s0", "s1", "s2"].map((id) => card(page, id).locator("[data-review-choice=accept]").count()));
      assert.deepEqual(texts, [1, 1, 1], "each has the same Accept control whatever its source");
    });
  },

  /**
   * The search box (docs/reference-search.md): words and meaning together, over References in any state, as ordinary cards that say how they matched.
   * A search is ordered by Relevance and opens on All without touching the saved Show; clearing it brings the saved choices back.
   */
  async search() {
    const shotDir = process.env.SEARCH_SHOTS;
    if (shotDir) fs.mkdirSync(shotDir, { recursive: true });
    const searches = (page: Page) => page.evaluate(() => window.searches.slice());
    const box = (page: Page) => page.locator("[data-feed-search-input]");
    const submit = async (page: Page, text: string) => { await box(page).fill(text); await box(page).press("Enter"); };
    const matched = (page: Page, id: string) => card(page, id).locator("[data-feed-matched]").innerText();
    const savedRated = async (page: Page) => { await page.addInitScript(() => localStorage.setItem("papyrus:reference-feed:show", "rated")); };
    const noSideScroll = async (page: Page) => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "no horizontal scroll");

    // The box sits above Sort and Show; Enter runs the search and puts it in the URL; each kind of match says so in words.
    await run("?search=1", [375, 1440], async (page, width) => {
      if (process.env.FEED_DEBUG) console.log(await page.locator("#root").innerHTML());
      await box(page).waitFor();
      const boxTop = (await page.locator("[data-feed-search]").boundingBox())!.y;
      const sortTop = (await page.locator("[data-feed-control=sort]").boundingBox())!.y;
      assert.ok(boxTop < sortTop, "the search box is above Sort and Show");
      assert.deepEqual(await searches(page), [], "nothing is searched until Enter");
      await submit(page, "Marta Okafor");
      await card(page, "rejected-by-author").waitFor();
      assert.deepEqual(await order(page), ["rejected-by-author"], "an exact author name finds a rejected Reference");
      assert.equal(await matched(page, "rejected-by-author"), "Matched: author");
      assert.equal(await card(page, "rejected-by-author").getAttribute("data-feed-rated"), "reject");
      assert.ok((await page.evaluate(() => location.search)).includes("q=Marta%20Okafor"), "the query is in the URL");
      assert.equal(await page.locator("[data-feed-lead]").count(), 0, "a search has no lead card");
      assert.equal(await page.locator("[data-feed-new-items]").count(), 0, "and no new-items pill");
      await submit(page, "notebooks");
      await card(page, "unrated-by-title").waitFor();
      assert.equal(await matched(page, "unrated-by-title"), "Matched: title");
      await submit(page, "memory");
      await card(page, "both").waitFor();
      assert.equal((await order(page))[0], "both", "a match on both lanes ranks first");
      assert.equal(await matched(page, "both"), "Matched: title and meaning");
      assert.equal(await matched(page, "accepted-meaning"), "Matched: meaning");
      assert.equal(await matched(page, "chips-history"), "Matched: title");
      assert.ok((await page.locator("[data-feed-matched]").first().innerText()).startsWith("Matched:"), "said in words, not colour alone");
      await noSideScroll(page);
      if (shotDir) await page.screenshot({ path: `${shotDir}/search-results-${width}.png` });
    });

    // Sort reads Relevance and Show opens on All while searching; the saved Show is not changed and comes back when the search is cleared.
    await run("?search=1", [375, 1440], async (page) => {
      await savedRated(page);
      await page.reload();
      await box(page).waitFor();
      assert.equal(await page.locator("[data-feed-show-button=rated]").getAttribute("aria-pressed"), "true", "the saved Show is Rated");
      await submit(page, "memory");
      await card(page, "both").waitFor();
      assert.equal(await page.locator("[data-feed-sort-relevance]").innerText(), "Relevance");
      assert.equal(await page.locator("[data-feed-sort-button=relevance]").getAttribute("aria-pressed"), "true", "Relevance is the chosen sort");
      assert.deepEqual(await page.locator("[data-feed-sort-button]").evaluateAll((buttons) => buttons.map((button) => button.getAttribute("data-feed-sort-button"))), ["relevance", "newest", "quality"], "no Predictions while searching");
      assert.equal(await page.locator("[data-feed-show-button=all]").getAttribute("aria-pressed"), "true", "the search opens on All");
      assert.equal((await searches(page))[0]!.show, "all");
      await page.locator("[data-feed-show-button=unrated]").click();
      await page.waitForFunction(() => window.searches.length === 2);
      assert.equal((await searches(page))[1]!.show, "unrated");
      await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length === 1);
      assert.deepEqual(await order(page), ["both"]);
      assert.equal(await page.evaluate(() => localStorage.getItem("papyrus:reference-feed:show")), "rated", "choosing Show during a search does not change the saved one");
      await page.locator("[data-feed-search-clear]").click();
      await page.locator("[data-feed-sort-button=best]").waitFor();
      assert.equal(await page.locator("[data-feed-show-button=rated]").getAttribute("aria-pressed"), "true", "clearing restores the saved Show");
      assert.equal(await page.evaluate(() => location.search), "", "and the URL loses ?q=");
      assert.equal(await page.locator("[data-feed-matched]").count(), 0);
    });

    // ?q= opens the page already searching.
    await run("?search=1&q=Okafor", [375], async (page) => {
      await card(page, "rejected-by-author").waitFor();
      assert.equal(await box(page).inputValue(), "Okafor");
    });

    // Nothing matches: said in words; with the Show filter narrowed the way out is a button.
    await run("?search=1", [375, 1440], async (page, width) => {
      await submit(page, "zzzz");
      assert.equal(await page.locator("[data-feed-empty]").innerText(), "No References match “zzzz”.");
      await submit(page, "okafor");
      await card(page, "rejected-by-author").waitFor();
      await page.locator("[data-feed-show-button=unrated]").click();
      await page.locator("[data-feed-search-empty]").waitFor();
      assert.ok((await page.locator("[data-feed-search-empty]").innerText()).startsWith("No matches with Reviewed No"));
      if (shotDir) await page.screenshot({ path: `${shotDir}/search-empty-filtered-${width}.png` });
      await page.locator("[data-feed-show-all]").click();
      await card(page, "rejected-by-author").waitFor();
      assert.equal(await page.locator("[data-feed-show-button=all]").getAttribute("aria-pressed"), "true");
    });

    // One lane down: the other's results stay, said in words, with a Retry that searches again. Both down: the feed's own error.
    await run("?search=1&lane=meaning-down", [375, 1440], async (page, width) => {
      await submit(page, "notebooks");
      await card(page, "unrated-by-title").waitFor();
      assert.equal((await page.locator("[data-feed-search-notice]").innerText()).split("\n")[0], "Searched by words only: meaning search is unavailable");
      const before = (await searches(page)).length;
      await page.locator("[data-feed-search-retry]").click();
      await page.waitForFunction((count) => window.searches.length > count, before);
      await card(page, "unrated-by-title").waitFor();
      if (shotDir) await page.screenshot({ path: `${shotDir}/search-meaning-down-${width}.png` });
    });
    await run("?search=1&laneOnce=1", [375], async (page) => {
      await submit(page, "notebooks");
      await page.locator("[data-feed-search-notice]").waitFor();
      await page.locator("[data-feed-search-retry]").click();
      await page.waitForFunction(() => document.querySelector("[data-feed-search-notice]") === null);
      assert.deepEqual(await order(page), ["unrated-by-title"], "after the retry both lanes ran");
    });
    await run("?search=1&lane=both-down", [375, 1440], async (page, width) => {
      await submit(page, "notebooks");
      await page.locator("[data-feed-error]").waitFor();
      assert.ok((await page.locator("[data-feed-error]").innerText()).includes("The References could not be loaded."));
      await page.locator("[data-feed-retry]").waitFor();
      if (shotDir) await page.screenshot({ path: `${shotDir}/search-both-down-${width}.png` });
    });

    // Paging: the existing infinite scroll asks for the next page with the site's cursor and never shows a card twice.
    await run("?search=1", [375, 1440], async (page) => {
      await submit(page, "shared topic");
      await cards(page).first().waitFor();
      await page.locator("[data-feed-more]").scrollIntoViewIfNeeded();
      await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length === 40);
      const ids = (await order(page)) as string[];
      assert.equal(new Set(ids).size, ids.length, "no card appears twice");
      const asked = await searches(page);
      assert.equal(asked.length, 2, "two pages of 24 cover 40 results");
      assert.equal(asked[0]!.cursor, null);
      assert.ok(asked[1]!.cursor, "the second page continues from the site's cursor");
      assert.equal(asked.every((entry) => entry.limit === 24), true);
    });

    // A card voted on stays where it is.
    await run("?search=1", [375], async (page) => {
      await submit(page, "shared topic");
      await cards(page).first().waitFor();
      const before = (await order(page)) as string[];
      const target = before[2]!;
      await card(page, target).locator("[data-review-choice=accept]").click();
      await page.waitForFunction((id) => document.querySelector(`[data-feed-card="${id}"]`)?.getAttribute("data-feed-rated") === "accept", target);
      assert.deepEqual((await order(page)).slice(0, before.length), before, "no card moved");
    });
  },

  /**
   * The Quality sort and the Minimum stars row (features/newsroom-reference-quality.feature): the star partitions are read and merged, Show and Sort
   * move with the choices as the rules say, the choices are saved, and a search takes the same row. Fixture site only.
   */
  async quality() {
    const shotDir = process.env.QUALITY_SHOTS;
    if (shotDir) fs.mkdirSync(shotDir, { recursive: true });
    const sortButton = (page: Page, key: string) => page.locator(`[data-feed-sort-button=${key}]`);
    const showButton = (page: Page, key: string) => page.locator(`[data-feed-show-button=${key}]`);
    const minButton = (page: Page, key: string) => page.locator(`[data-feed-min-stars-button="${key}"]`);
    const pressed = async (button: ReturnType<typeof sortButton>) => (await button.getAttribute("aria-pressed")) === "true";
    const waitOrder = async (page: Page, expected: string[]) => {
      await page.waitForFunction((ids) => JSON.stringify(Array.from(document.querySelectorAll("[data-feed-card]")).map((element) => element.getAttribute("data-feed-card"))) === JSON.stringify(ids), expected);
      assert.deepEqual(await order(page), expected);
    };
    const requests = (page: Page) => page.evaluate(() => window.requests.slice());
    const searches = (page: Page) => page.evaluate(() => window.searches.slice());
    const stored = (page: Page, key: string) => page.evaluate((name) => localStorage.getItem(`papyrus:reference-feed:${name}`), key);
    const noSideScroll = async (page: Page) => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "no horizontal scroll");
    const QUALITY = ["five-new", "five-old", "four-new", "four-old", "three", "two", "one"];

    await run("?quality=1", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      // The controls: a third sort, and a labelled row of minimums with a star and a number, none of them with a border.
      assert.deepEqual(await page.locator("[data-feed-sort-button]").evaluateAll((buttons) => buttons.map((button) => button.textContent)), ["Predictions", "Newest", "Quality"]);
      const row = page.locator("[data-feed-control=min-stars]");
      assert.ok((await row.innerText()).startsWith("Minimum stars"));
      assert.deepEqual(await page.locator("[data-feed-min-stars-button]").evaluateAll((buttons) => buttons.map((button) => (button.textContent ?? "").trim())), ["Any", "3+ stars or more", "4+ stars or more", "5 stars"]);
      assert.deepEqual(await page.locator("[data-feed-min-stars-button]").evaluateAll((buttons) => buttons.map((button) => button.querySelectorAll("svg").length)), [0, 1, 1, 1], "a star icon with the number; Any has none");
      assert.equal(await pressed(sortButton(page, "best")) && await pressed(showButton(page, "unrated")) && await pressed(minButton(page, "0")), true, "Predictions, Unrated and Any by default");
      const borders = await page.locator("[data-feed-control=min-stars], [data-feed-control=min-stars] *").evaluateAll((elements) => elements.map((element) => {
        const style = getComputedStyle(element);
        return ["Top", "Right", "Bottom", "Left"].map((side) => style.getPropertyValue(`border-${side.toLowerCase()}-width`)).join(" ");
      }));
      assert.ok(borders.every((value) => value === "0px 0px 0px 0px"), "no borders on the new controls: " + borders.join(" | "));
      await noSideScroll(page);
      if (shotDir) await page.screenshot({ path: `${shotDir}/quality-controls-${width}.png` });

      // Quality: most stars first, newest first within a star level; only starred, never an archived or superseded Reference. Show moves to All, in view.
      await sortButton(page, "quality").click();
      await waitOrder(page, QUALITY);
      assert.equal(await pressed(showButton(page, "all")), true, "Unrated moved to All, visibly");
      assert.equal(await pressed(sortButton(page, "quality")), true);
      const read = (await requests(page)).filter((request) => request.kind === "stars").map((request) => request.key);
      assert.deepEqual([...new Set(read)].sort(), ["c", "d"].flatMap((corpus) => [1, 2, 3, 4, 5].map((n) => `${corpus}#stars#${n}`)).sort(), "every star level of every corpus");
      assert.equal(await cards(page).count(), 7);
      assert.equal(await stored(page, "show"), "all", "the move is saved like any choice of Show");
      if (shotDir) await page.screenshot({ path: `${shotDir}/quality-sort-${width}.png` });

      // Show is the editor's afterwards.
      await showButton(page, "unrated").click();
      await waitOrder(page, ["five-old", "four-old", "one"]);
      await showButton(page, "rated").click();
      await waitOrder(page, ["five-new", "four-new", "three", "two"]);
      await showButton(page, "all").click();
      await waitOrder(page, QUALITY);

      // 4+ on Newest merges the 5 and 4 star partitions by arrival, and reads no other level.
      await sortButton(page, "newest").click();
      const before = (await requests(page)).length;
      await minButton(page, "4").click();
      await waitOrder(page, ["five-new", "four-new", "five-old", "four-old"]);
      assert.equal(await pressed(minButton(page, "4")), true);
      const merged = (await requests(page)).slice(before).filter((request) => request.kind === "stars").map((request) => request.key);
      assert.deepEqual([...new Set(merged)].sort(), ["c#stars#4", "c#stars#5", "d#stars#4", "d#stars#5"]);
      assert.equal((await requests(page)).slice(before).filter((request) => request.kind === "index").length, 0, "the feed-state index is not read for a minimum");
      if (shotDir) await page.screenshot({ path: `${shotDir}/quality-minimum-${width}.png` });
      await minButton(page, "5").click();
      await waitOrder(page, ["five-new", "five-old"]);
      await minButton(page, "3").click();
      await waitOrder(page, ["five-new", "four-new", "three", "five-old", "four-old"]);

      // A minimum survives a reload, with Sort and Show.
      await minButton(page, "4").click();
      await waitOrder(page, ["five-new", "four-new", "five-old", "four-old"]);
      await page.reload();
      await minButton(page, "4").waitFor();
      await page.waitForFunction(() => document.querySelector("[data-feed-min-stars-button='4']")?.getAttribute("aria-pressed") === "true");
      assert.equal(await pressed(sortButton(page, "newest")), true);
      assert.equal(await pressed(showButton(page, "all")), true);
      await waitOrder(page, ["five-new", "four-new", "five-old", "four-old"]);

      // Predictions takes the minimum back to Any.
      await sortButton(page, "best").click();
      await page.waitForFunction(() => document.querySelector("[data-feed-min-stars-button='0']")?.getAttribute("aria-pressed") === "true");
      assert.equal(await pressed(sortButton(page, "best")), true);
      assert.equal(await stored(page, "min-stars"), "0");
      await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length === 9);
      // And a minimum takes Predictions to Newest, and Unrated to All.
      await showButton(page, "unrated").click();
      await page.waitForFunction(() => document.querySelector("[data-feed-show-button='unrated']")?.getAttribute("aria-pressed") === "true");
      await minButton(page, "3").click();
      await waitOrder(page, ["five-new", "four-new", "three", "five-old", "four-old"]);
      assert.equal(await pressed(sortButton(page, "newest")), true, "a minimum moves Predictions to Newest");
      assert.equal(await pressed(showButton(page, "all")), true, "and Unrated to All");
      await noSideScroll(page);
    });

    // A minimum that finds nothing is named, with a way to take it off.
    await run("?quality=1&noFive=1", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      await minButton(page, "5").click();
      await page.locator("[data-feed-min-stars-empty]").waitFor();
      assert.equal((await page.locator("[data-feed-min-stars-empty]").innerText()).replace(/\n+/g, " / "), "Nothing here has 5 stars. / Show any stars");
      if (shotDir) await page.screenshot({ path: `${shotDir}/quality-empty-${width}.png` });
      await page.locator("[data-feed-min-stars-clear]").click();
      await cards(page).first().waitFor();
      assert.equal(await pressed(minButton(page, "0")), true);
      assert.equal(await page.locator("[data-feed-min-stars-empty]").count(), 0);
    });

    // A search takes the same row, and has Newest and Quality of its own, opened on Relevance and not saved.
    await run("?quality=1", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      await page.locator("[data-feed-search-input]").fill("quality topic");
      await page.locator("[data-feed-search-input]").press("Enter");
      await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length === 9);
      assert.deepEqual(await page.locator("[data-feed-sort-button]").evaluateAll((buttons) => buttons.map((button) => button.textContent)), ["Relevance", "Newest", "Quality"]);
      assert.equal(await pressed(sortButton(page, "relevance")), true, "a search opens on Relevance");
      await sortButton(page, "newest").click();
      await waitOrder(page, ["plain-new", "five-new", "four-new", "three", "two", "one", "five-old", "four-old", "plain-old"]);
      assert.deepEqual((await searches(page)).at(-1), { query: "quality topic", show: "all", limit: 24, cursor: null, sort: "newest", minStars: null, captured: "any" });
      await sortButton(page, "quality").click();
      await waitOrder(page, [...QUALITY, "plain-new", "plain-old"]);
      assert.equal((await searches(page)).at(-1)!.sort, "quality");
      if (shotDir) await page.screenshot({ path: `${shotDir}/quality-search-${width}.png` });
      await minButton(page, "4").click();
      await waitOrder(page, ["five-new", "five-old", "four-new", "four-old"]);
      assert.deepEqual({ sort: (await searches(page)).at(-1)!.sort, minStars: (await searches(page)).at(-1)!.minStars }, { sort: "quality", minStars: 4 });
      assert.equal(await pressed(sortButton(page, "quality")), true, "the search keeps its own sort");
      assert.equal(await stored(page, "min-stars"), "4", "the minimum is the shared saved one");
      await minButton(page, "0").click();
      await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length === 9);
      // Unrated while searching, then Quality or a minimum: Show moves to All.
      await showButton(page, "unrated").click();
      await page.waitForFunction(() => document.querySelector("[data-feed-show-button='unrated']")?.getAttribute("aria-pressed") === "true");
      await minButton(page, "3").click();
      assert.equal(await pressed(showButton(page, "all")), true, "a minimum moves the search's Unrated to All");
      await page.waitForFunction(() => document.querySelector("[data-feed-search-input]") !== null);
      // Clearing the search brings back the saved choices.
      await page.locator("[data-feed-search-clear]").click();
      await sortButton(page, "best").waitFor().catch(() => undefined);
      assert.equal(await pressed(minButton(page, "3")), true);
      assert.equal(await pressed(sortButton(page, "newest")), true, "the saved Predictions moved to Newest with the minimum");
      assert.equal(await page.locator("[data-feed-sort-relevance]").count(), 0);
    });

    // A page of star rows that all filter away does not stop the feed: scrolling goes on until the live rows come.
    await run("?quality=1&ghosts=1", [375], async (page) => {
      await cards(page).first().waitFor();
      await sortButton(page, "quality").click();
      await waitOrder(page, QUALITY);
      const reads = (await requests(page)).filter((request) => request.kind === "stars" && request.key === "c#stars#5").length;
      assert.ok(reads >= 3, "three pages of the 5 star partition were read to get past 60 archived rows, got " + reads);
    });
  },

  /**
   * Reviewed (Any, Accepted, Yes, No) and Captured (Any, Yes, No): the words, the buttons, the filtering of the feed and of a search, the saved
   * choice, a page address that opens a view without saving it, the empty state, and a run of filtered pages that does not end the list.
   */
  async captured() {
    const shotDir = process.env.CAPTURE_SHOTS;
    if (shotDir) fs.mkdirSync(shotDir, { recursive: true });
    const button = (page: Page, kind: string, key: string) => page.locator(`[data-feed-${kind}-button="${key}"]`);
    const pressed = async (page: Page, kind: string, key: string) => (await button(page, kind, key).getAttribute("aria-pressed")) === "true";
    const waitOrder = async (page: Page, expected: string[]) => {
      await page.waitForFunction((ids) => JSON.stringify(Array.from(document.querySelectorAll("[data-feed-card]")).map((element) => element.getAttribute("data-feed-card"))) === JSON.stringify(ids), expected, { timeout: 8000 });
      assert.deepEqual(await order(page), expected);
    };
    const noSideScroll = async (page: Page) => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "no horizontal scroll");
    const searches = (page: Page) => page.evaluate(() => window.searches.slice());

    await run("?quality=1", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      // The words: a labelled row for Reviewed and one for Captured, each a group of buttons with an icon and words; no drop-downs, no borders.
      assert.ok((await page.locator("[data-feed-control=show]").innerText()).startsWith("Reviewed"));
      assert.ok((await page.locator("[data-feed-control=captured]").innerText()).startsWith("Captured"));
      assert.deepEqual(await page.locator("[data-feed-show-button]").evaluateAll((buttons) => buttons.map((b) => (b.textContent ?? "").trim())), ["Any", "Accepted", "Yes", "No"]);
      assert.deepEqual(await page.locator("[data-feed-show-button]").evaluateAll((buttons) => buttons.map((b) => b.getAttribute("data-feed-show-button"))), ["all", "accepted", "rated", "unrated"], "the saved values keep their names");
      assert.deepEqual(await page.locator("[data-feed-captured-button]").evaluateAll((buttons) => buttons.map((b) => (b.textContent ?? "").trim())), ["Any", "Yes", "No"]);
      for (const selector of ["[data-feed-show-button]", "[data-feed-captured-button]"]) {
        for (const each of await page.locator(selector).all()) assert.ok((await each.locator("svg").count()) >= 1, "a Lucide icon beside the words");
      }
      assert.equal(await page.locator("select").count(), 0, "no drop-downs");
      assert.equal(await pressed(page, "captured", "any"), true, "Captured is Any by default");
      assert.equal(await pressed(page, "show", "unrated"), true, "Reviewed is No by default");
      const borders = await page.locator("[data-feed-control=show] *, [data-feed-control=captured] *").evaluateAll((elements) => elements.filter((element) => {
        const style = getComputedStyle(element);
        return ["Top", "Right", "Bottom", "Left"].some((side) => parseFloat((style as unknown as Record<string, string>)[`border${side}Width`]) > 0 && (style as unknown as Record<string, string>)[`border${side}Style`] !== "none");
      }).length);
      assert.equal(borders, 0, "no borders on the new controls");
      await noSideScroll(page);
      if (shotDir) await page.screenshot({ path: `${shotDir}/capture-controls-${width}.png` });

      // Quality shows every starred card; Reviewed moves from No to Any with it (the existing rule).
      await page.locator("[data-feed-sort-button=quality]").click();
      assert.equal(await pressed(page, "show", "all"), true, "Quality moved Reviewed to Any");
      await waitOrder(page, ["five-new", "five-old", "four-new", "four-old", "three", "two", "one"]);
      await button(page, "captured", "no").click();
      assert.equal(await pressed(page, "captured", "no"), true);
      await waitOrder(page, ["five-new", "four-new", "four-old", "two", "one"]);   // thin, none, empty and running are all not captured
      await button(page, "captured", "yes").click();
      await waitOrder(page, ["five-old", "three"]);
      await button(page, "captured", "any").click();
      await button(page, "show", "accepted").click();
      await waitOrder(page, ["five-new", "three", "two"]);   // the rejected one is not here
      await button(page, "captured", "no").click();
      await waitOrder(page, ["five-new", "two"]);   // accepted, not captured, including one still being captured
      await button(page, "show", "rated").click();
      await button(page, "captured", "any").click();
      await waitOrder(page, ["five-new", "four-new", "three", "two"]);   // Yes is accepted or rejected
      assert.equal(await page.evaluate(() => localStorage.getItem("papyrus:reference-feed:show")), "rated");

      // The choices are remembered in this browser.
      await button(page, "captured", "no").click();
      await page.reload();
      await cards(page).first().waitFor();
      assert.equal(await page.evaluate(() => localStorage.getItem("papyrus:reference-feed:captured")), "no");
      assert.equal(await pressed(page, "captured", "no"), true, "Captured is remembered");
      assert.equal(await pressed(page, "show", "rated"), true, "and so is Reviewed");

      // The empty state names what found nothing, and offers a way out.
      await button(page, "show", "accepted").click();
      await page.locator("[data-feed-min-stars-button='5']").click();
      await button(page, "captured", "yes").click();
      await page.locator("[data-feed-captured-empty]").waitFor();
      assert.equal((await page.locator("[data-feed-captured-empty]").innerText()).replace(/\n+/g, " / "), "Nothing here has 5 stars and has been captured. / Show any stars / Show any Captured");
      if (shotDir) await page.screenshot({ path: `${shotDir}/capture-empty-${width}.png` });
      await page.locator("[data-feed-captured-clear]").click();
      await waitOrder(page, ["five-new"]);   // accepted with 5 stars, whether captured or not
      assert.equal(await page.locator("[data-feed-empty]").count(), 0);
    });

    // A search takes Captured and Reviewed Accepted too.
    await run("?quality=1", [375], async (page) => {
      await cards(page).first().waitFor();
      await button(page, "captured", "no").click();
      await page.locator("[data-feed-search-input]").fill("Quality topic");
      await page.keyboard.press("Enter");
      await page.waitForFunction(() => window.searches.length > 0);
      assert.equal((await searches(page))[0]!.captured, "no", "the search is asked for Captured No");
      await waitOrder(page, ["five-new", "four-new", "two", "one", "four-old", "plain-old"]);
      await button(page, "show", "accepted").click();
      await waitOrder(page, ["five-new", "two"]);
      assert.equal((await searches(page)).at(-1)!.show, "accepted");
      assert.equal(await page.evaluate(() => localStorage.getItem("papyrus:reference-feed:show")), null, "choosing Reviewed during a search is not saved");
    });

    // A page address opens a view for this visit without saving it (the home page's See all).
    await run("?quality=1&reviewed=accepted&captured=no&sort=quality&minStars=0", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      assert.equal(await pressed(page, "show", "accepted"), true);
      assert.equal(await pressed(page, "captured", "no"), true);
      assert.equal(await pressed(page, "sort", "quality"), true);
      await waitOrder(page, ["five-new", "two"]);
      for (const key of ["show", "captured", "sort", "min-stars"]) assert.equal(await page.evaluate((name) => localStorage.getItem(`papyrus:reference-feed:${name}`), key), null, `${key} was not saved`);
      await button(page, "captured", "any").click();
      assert.equal(await page.evaluate(() => localStorage.getItem("papyrus:reference-feed:captured")), null, "changing a control inside an address-chosen view does not save either");
      await waitOrder(page, ["five-new", "three", "two"]);
      if (shotDir) await page.screenshot({ path: `${shotDir}/capture-see-all-view-${width}.png` });
    });

    // Sixty filtered rows ahead of the three that match: scrolling goes on until they come.
    await run("?quality=1&filtered=1", [375], async (page) => {
      await cards(page).first().waitFor();
      await page.locator("[data-feed-sort-button=newest]").click();
      await button(page, "captured", "no").click();
      await page.waitForFunction(() => document.querySelectorAll("[data-feed-card^='tail-']").length === 3, undefined, { timeout: 15000 });
      const ids = await order(page);
      assert.ok(ids.includes("tail-0") && ids.includes("tail-2"), "the cards behind sixty filtered rows were reached");
      assert.ok(!ids.some((id) => id?.startsWith("held-")), "none of the captured ones is shown");
    });
  },

  /**
   * Medium (All, Videos): the words, the buttons, the reads (only the medium partitions, never the feed-state index), the combination with Reviewed,
   * stars and Captured, the address, and the empty state.
   */
  async medium() {
    const shotDir = process.env.MEDIUM_SHOTS;
    if (shotDir) fs.mkdirSync(shotDir, { recursive: true });
    const button = (page: Page, kind: string, key: string) => page.locator(`[data-feed-${kind}-button="${key}"]`);
    const pressed = async (page: Page, kind: string, key: string) => (await button(page, kind, key).getAttribute("aria-pressed")) === "true";
    const waitOrder = async (page: Page, expected: string[]) => {
      await page.waitForFunction((ids) => JSON.stringify(Array.from(document.querySelectorAll("[data-feed-card]")).map((element) => element.getAttribute("data-feed-card"))) === JSON.stringify(ids), expected, { timeout: 8000 });
      assert.deepEqual(await order(page), expected);
    };
    const requests = (page: Page) => page.evaluate(() => window.requests.slice());
    const search = (page: Page) => page.evaluate(() => location.search);
    const noSideScroll = async (page: Page) => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "no horizontal scroll");

    // The words and the controls: a labelled row of two buttons with an icon each, no drop-down, no border; All is pressed by default.
    await run("?quality=1&videos=1", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      assert.ok((await page.locator("[data-feed-control=medium]").innerText()).startsWith("Medium"));
      assert.deepEqual(await page.locator("[data-feed-medium-button]").evaluateAll((buttons) => buttons.map((b) => (b.textContent ?? "").trim())), ["All", "Videos"]);
      assert.deepEqual(await page.locator("[data-feed-medium-button]").evaluateAll((buttons) => buttons.map((b) => b.getAttribute("data-feed-medium-button"))), ["any", "video"]);
      for (const each of await page.locator("[data-feed-medium-button]").all()) assert.ok((await each.locator("svg").count()) >= 1, "a Lucide icon beside the words");
      assert.equal(await page.locator("select").count(), 0, "no drop-downs");
      assert.equal(await pressed(page, "medium", "any"), true, "All is pressed by default");
      const borders = await page.locator("[data-feed-control=medium], [data-feed-control=medium] *").evaluateAll((elements) => elements.filter((element) => {
        const style = getComputedStyle(element);
        return ["Top", "Right", "Bottom", "Left"].some((side) => parseFloat((style as unknown as Record<string, string>)[`border${side}Width`]) > 0 && (style as unknown as Record<string, string>)[`border${side}Style`] !== "none");
      }).length);
      assert.equal(borders, 0, "no borders on the Medium buttons");
      await noSideScroll(page);
      // The fixture has no publication theme: give the feed tones values like a light theme's, so a screenshot shows the chosen button.
      if (shotDir) await page.addStyleTag({ content: "[data-feed-surface]{--feed-card:#f3f1e6;--feed-footer:#ebe8d8;--feed-control:#dcd9c4;--foreground:#1c1b14;--muted-foreground:#6b6a5c}" });
      if (shotDir) { await page.waitForTimeout(500); await page.screenshot({ path: `${shotDir}/medium-all-${width}.png` }); }

      // Videos: two clicks to the pending videos (Reviewed is No by default), read from the medium partitions alone.
      await page.evaluate(() => { window.requests.length = 0; });
      await button(page, "medium", "video").click();
      assert.equal(await pressed(page, "medium", "video"), true);
      await waitOrder(page, ["video-new", "video-other-corpus", "video-old"]);
      assert.equal(await search(page), "?quality=1&videos=1&medium=video", "the choice is in the address, the rest of it kept");
      const reads = await requests(page);
      assert.deepEqual([...new Set(reads.map((request) => request.kind))], ["medium"], "no feed-state or star partition was read");
      assert.deepEqual([...new Set(reads.map((request) => request.key))].sort(), ["c#video#pending", "d#video#pending"]);
      assert.equal(await pressed(page, "sort", "newest"), true, "the medium index is by arrival, so Newest shows pressed");
      assert.equal(await page.evaluate(() => localStorage.getItem("papyrus:reference-feed:sort")), null, "the saved Sort was not changed");
      assert.equal(await page.locator("[data-feed-card='plain-new']").count(), 0, "an article with no medium is not listed");
      if (shotDir) { await page.waitForTimeout(500); await page.screenshot({ path: `${shotDir}/medium-videos-${width}.png` }); }

      // Reviewed picks the vote partitions.
      await button(page, "show", "all").click();
      await waitOrder(page, ["video-new", "video-other-corpus", "video-accepted", "video-rejected", "video-starred", "video-old"]);
      await button(page, "show", "accepted").click();
      await waitOrder(page, ["video-accepted", "video-starred"]);
      await button(page, "show", "rated").click();
      await waitOrder(page, ["video-accepted", "video-rejected", "video-starred"]);
      assert.deepEqual([...new Set((await requests(page)).map((request) => request.key))].sort(), [
        "c#video#accepted", "c#video#pending", "c#video#rejected", "d#video#accepted", "d#video#pending", "d#video#rejected",
      ]);
      assert.ok((await requests(page)).every((request) => request.kind === "medium"), "every read was a medium partition");

      // Stars read the small star partitions and keep the videos in them.
      await button(page, "min-stars", "3").click();
      await waitOrder(page, ["video-starred"]);
      await button(page, "min-stars", "0").click();

      // Captured applies on top; an empty answer says so in words, with a way out.
      await button(page, "show", "all").click();
      await button(page, "captured", "yes").click();
      await page.locator("[data-feed-medium-empty]").waitFor();
      assert.equal((await page.locator("[data-feed-medium-empty]").innerText()).replace(/\n+/g, " / "), "No videos with Reviewed Any and Captured Yes. / Show all media");
      if (shotDir) { await page.waitForTimeout(500); await page.screenshot({ path: `${shotDir}/medium-empty-${width}.png` }); }
      await button(page, "captured", "any").click();
      await waitOrder(page, ["video-new", "video-other-corpus", "video-accepted", "video-rejected", "video-starred", "video-old"]);

      // All takes it off the address and lists everything again; the video buttons are not saved anywhere.
      await button(page, "medium", "any").click();
      assert.equal(await search(page), "?quality=1&videos=1");
      await page.locator("[data-feed-card='plain-new']").waitFor();
      assert.equal(await page.evaluate(() => Object.keys(localStorage).some((key) => key.includes("medium"))), false);
    });

    // Predictions cannot order a medium: choosing it goes back to All.
    await run("?quality=1&videos=1&medium=video", [375], async (page) => {
      await cards(page).first().waitFor();
      assert.equal(await pressed(page, "medium", "video"), true, "the address opens on Videos");
      await waitOrder(page, ["video-new", "video-other-corpus", "video-old"]);
      await page.locator("[data-feed-sort-button=quality]").click();
      await waitOrder(page, ["video-starred"]);   // Quality: Reviewed moved to Any, only starred videos
      assert.equal(await pressed(page, "medium", "video"), true);
      await page.locator("[data-feed-sort-button=best]").click();
      assert.equal(await pressed(page, "medium", "any"), true, "Predictions took the medium off");
      assert.equal(await search(page), "?quality=1&videos=1");
    });

    // A search does not use the medium: the row is out of the way while one is open.
    await run("?quality=1&videos=1&medium=video", [375], async (page) => {
      await cards(page).first().waitFor();
      await page.locator("[data-feed-search-input]").fill("Quality topic");
      await page.keyboard.press("Enter");
      await page.waitForFunction(() => window.searches.length > 0);
      assert.equal(await page.locator("[data-feed-control=medium]").count(), 0);
    });

    // A value the page does not know is All.
    await run("?quality=1&videos=1&medium=podcast", [375], async (page) => {
      await cards(page).first().waitFor();
      assert.equal(await pressed(page, "medium", "any"), true);
    });
  },

  /** A refused save is said in words and the card keeps its place. */
  async refusal() {
    await run("?fail=1", [375], async (page) => {
      await cards(page).first().waitFor();
      await card(page, "mid-accept").locator("[data-review-choice=accept]").click();
      assert.ok((await card(page, "mid-accept").locator("[role=alert]").innerText()).includes("The backend refused this."));
      assert.equal(await card(page, "mid-accept").getAttribute("data-feed-rated"), null);
    });
    await run("?disabled=Editor%20access%20is%20required.", [375], async (page) => {
      await cards(page).first().waitFor();
      await card(page, "mid-accept").locator("[data-review-choice=accept]").click({ force: true });
      assert.ok((await card(page, "mid-accept").locator("[data-review-disabled-reason]").innerText()).includes("Editor access is required."));
      assert.equal(await page.evaluate(() => (window as unknown as { calls: unknown[] }).calls.length), 0);
    });
  },
};

async function main() {
  const requested = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested && requested !== name) continue;
    await scenario();
    console.log(`Reference feed scenario passed: ${name}`);
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
