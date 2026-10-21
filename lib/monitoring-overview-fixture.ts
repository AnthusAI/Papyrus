import type { MonitoringOverview } from "./monitoring-overview";

/** A realistic overview for tests and the `?demo=1` newsroom. Public Hacker News titles only. */
export const FIXTURE_MONITORING_OVERVIEW: MonitoringOverview = {
  state: "ready",
  asOf: "2026-10-21T02:40:00Z",
  scope: { mode: "publication", publicationId: "desk-a", site: "a.example.test", canViewAll: true },
  feeds: [{ id: "hn", sourceUrl: "https://news.ycombinator.com/rss", intervalSeconds: 900, limit: 30, enabled: true,
    lastStatus: "complete", lastFinishedAt: "2026-10-21T02:33:00Z", nextDueAt: "2026-10-21T02:50:00Z" }],
  runs: [
    { runId: "r3", startedAt: "2026-10-21T02:33:00.000000Z", status: "complete", new: 2, revised: 1, unchanged: 27, itemCount: 30, errorCount: 0, errors: [] },
    { runId: "r1", startedAt: "2026-10-21T02:18:00.000000Z", status: "complete", new: 0, revised: 0, unchanged: 30, itemCount: 30, errorCount: 0, errors: [] },
    { runId: "r0", startedAt: "2026-10-21T02:03:00.000000Z", status: "partial", new: 1, revised: 0, unchanged: 28, itemCount: 30, errorCount: 1, errors: ["ConnectionError: timeout"] },
  ],
  routerRuns: [{ runId: "q2", startedAt: "2026-10-21T02:37:00.000000Z", mode: "live", status: "stopped", stoppedBy: "request_ceiling_reached",
    counts: { examined: 3, decided: 1, delivered: 1, deliveryFailed: 1, routed: 1 }, errorCount: 0 }],
  router: { mode: "live", feedback: true, enabled: true, maxItemsPerRun: 5 },
  usage: { day: "2026-10-21", decisionsToday: 2, decisionsTotal: 3, ceilings: { decisionsTotal: 300, decisionsPerDay: 100, items: 300 } },
  hiddenNotRelevant: 1,
  items: [
    { sourceId: "104", revision: 1, title: "Fresh Show HN", url: "https://example.org/104", discussionUrl: "https://news.ycombinator.com/item?id=104",
      observedAt: "2026-10-21T02:30:00.000000Z", routing: "collected", routingNote: null, decidedAt: null,
      relevance: [{ publicationId: "desk-a", site: "a.example.test", relevant: null, label: null, confidence: null, delivery: { state: null } }] },
    { sourceId: "105", revision: 1, title: "Broken request", url: "https://example.org/105", discussionUrl: "https://news.ycombinator.com/item?id=105",
      observedAt: "2026-10-21T01:30:00.000000Z", routing: "error", routingNote: "invalid request: bad title", decidedAt: null,
      relevance: [{ publicationId: "desk-a", site: "a.example.test", relevant: null, label: null, confidence: null, delivery: { state: null } }] },
    { sourceId: "101", revision: 1, title: "Quantum paper on arXiv", url: "https://example.org/101", discussionUrl: "https://news.ycombinator.com/item?id=101",
      observedAt: "2026-10-21T00:10:00.000000Z", routing: "routed", routingNote: null, decidedAt: "2026-10-21T01:00:00Z",
      relevance: [{ publicationId: "desk-a", site: "a.example.test", relevant: true, label: "include", confidence: 0.91,
        delivery: { state: "delivered", referenceId: "ref-1", referenceLineageId: "lin-1", deliveredAt: "2026-10-21T01:00:05Z" } }] },
    { sourceId: "103", revision: 1, title: "Phishing kit leaks", url: "https://example.org/103", discussionUrl: "https://news.ycombinator.com/item?id=103",
      observedAt: "2026-10-20T23:00:00.000000Z", routing: "decided", routingNote: null, decidedAt: "2026-10-20T23:10:00Z",
      relevance: [{ publicationId: "desk-a", site: "a.example.test", relevant: true, label: "include", confidence: 0.7,
        delivery: { state: "failed", error: "ClientError: throttled", attempts: 2 } }] },
  ],
};

export const FIXTURE_ALL_PIPELINE_OVERVIEW: MonitoringOverview = {
  ...FIXTURE_MONITORING_OVERVIEW,
  scope: { mode: "all", publicationId: "desk-a", site: "a.example.test", canViewAll: true },
  hiddenNotRelevant: 0,
  items: FIXTURE_MONITORING_OVERVIEW.items.map((item) => item.sourceId !== "101" ? item : {
    ...item,
    relevance: [
      ...item.relevance,
      { publicationId: "desk-b", site: "b.example.test", relevant: false, label: "exclude", confidence: 0.8, delivery: { state: "not_applicable" } },
      { publicationId: "desk-c", site: "desk-c", relevant: true, label: "include", confidence: null,
        delivery: { state: "delivered", referenceId: "ref-2", referenceLineageId: "lin-2" } },
    ],
  }),
};
