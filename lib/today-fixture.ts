import type { TodayAttentionEntry, TodayCounts, TodayDue, TodayOverdue, TodayOverview, TodayReview, TodayRow, TodayRun } from "./today-overview";

const none: TodayCounts = { acted: 0, nothing: 0, asked: 0, failed: 0, unknown: 0, notFinished: 0, beforeOutcomes: 0 };

function run(id: string, at: string, fields: Partial<TodayRun>): TodayRun {
  return {
    runId: id, procedureKey: "example.procedure", automationId: null, requestedAt: at, finishedAt: null, runStatus: "completed", outcome: "acted",
    outcomeReason: null, outcomeShown: "✓ Did it", rung: null, subjectKind: null, subjectId: null, costUsd: null, error: null, ...fields,
  };
}

const rate: TodayRow = {
  key: "responsibility:rate", kind: "responsibility", title: "Rate and curate", counts: { ...none, acted: 6, nothing: 1, asked: 1 },
  reasons: { nothing: { not_rated: 1 }, asked: { needs_review: 1 } }, automationIds: ["rate.new-references"], costUsd: 0.02, costKnownRuns: 8, costUnknownRuns: 0,
  runs: [
    ...[1, 2, 3, 4].map((n) => run(`run-r0${n}`, `2026-11-16T1${n}:00:00.000Z`, { automationId: "rate.new-references", costUsd: 0.0025 })),
    run("run-r1", "2026-11-16T14:05:00.000Z", { automationId: "rate.new-references", costUsd: 0.0025 }),
    run("run-r2", "2026-11-16T15:10:00.000Z", { automationId: "rate.new-references", outcome: "nothing", outcomeReason: "not_rated", outcomeShown: "– Nothing to do (not_rated)", costUsd: 0 }),
    run("run-r3", "2026-11-16T16:20:00.000Z", { automationId: "rate.new-references", outcome: "asked", outcomeReason: "needs_review", outcomeShown: "? Asked (needs_review)", costUsd: 0.0025 }),
    run("run-r4", "2026-11-16T16:40:00.000Z", { automationId: "rate.new-references", costUsd: 0.0025 }),
  ],
};
const translate: TodayRow = {
  key: "responsibility:translate", kind: "responsibility", title: "Translate", counts: { ...none, acted: 2, failed: 1, unknown: 1 },
  reasons: { failed: { timed_out: 1 }, unknown: { no_result_recorded: 1 } }, automationIds: [], costUsd: 0.41, costKnownRuns: 3, costUnknownRuns: 1,
  runs: [
    run("run-t1", "2026-11-16T13:00:00.000Z", { costUsd: 0.25 }),
    run("run-t2", "2026-11-16T13:30:00.000Z", { runStatus: "failed", outcome: "failed", outcomeReason: "timed_out", outcomeShown: "✗ Failed (timed_out)", costUsd: 0.16, error: "timed out after 840 s" }),
    run("run-t0", "2026-11-16T12:30:00.000Z", { costUsd: 0 }),
    run("run-t3", "2026-11-16T14:30:00.000Z", { runStatus: "failed", outcome: "unknown", outcomeReason: "no_result_recorded", outcomeShown: "! Outcome unknown (no_result_recorded)" }),
  ],
};
const announce: TodayRow = {
  key: "responsibility:announce", kind: "responsibility", title: "Announce", counts: { ...none, nothing: 3 },
  reasons: { nothing: { not_rated: 2, under_channel_bar: 1 } }, automationIds: ["announce.releases"], costUsd: 0, costKnownRuns: 3, costUnknownRuns: 0,
  runs: [
    run("run-a1", "2026-11-16T12:00:00.000Z", { automationId: "announce.releases", outcome: "nothing", outcomeReason: "not_rated", outcomeShown: "– Nothing to do (not_rated)", costUsd: 0 }),
    run("run-a2", "2026-11-16T13:00:00.000Z", { automationId: "announce.releases", outcome: "nothing", outcomeReason: "not_rated", outcomeShown: "– Nothing to do (not_rated)", costUsd: 0 }),
    run("run-a3", "2026-11-16T14:00:00.000Z", { automationId: "announce.releases", outcome: "nothing", outcomeReason: "under_channel_bar", outcomeShown: "– Nothing to do (under_channel_bar)", costUsd: 0 }),
  ],
};

const overdueDelivery: TodayOverdue = {
  kind: "Delivery", id: "announcement-daily#email#site#g1", dueAt: "2026-11-16T11:00:00Z", waitingFor: "release", flagId: "overdue-0f3a",
  shown: "⏰ Overdue: Delivery announcement-daily#email#site#g1 was due 2026-11-16T11:00:00Z (release) and nothing ran",
};

const waiting: TodayReview[] = [
  {
    kind: "review", id: "gate-run-announce-7", mode: "hard_gate", modeWords: "Hard gate: nothing proceeds without an answer", mark: "?",
    reason: "Post the X announcement of \"Agents that lie\"?", ask: "Approve or do: post", subject: { type: "automation_run", id: "run-announce-7" },
    subjectWords: "automation run run-announce-7", raisedBy: "agent:announce", raisedAt: "2026-11-16T14:10:00Z", deadline: null, deadlineLocal: null,
    action: { kind: "answer", words: "Answer", requestId: "gate-run-announce-7", command: "papyrus reviews answer --id gate-run-announce-7 --decision approve|reject" },
  },
  {
    kind: "review", id: "announce-draft-x-1", mode: "soft_review", modeWords: "Soft review", mark: "?",
    reason: "X announcement draft for \"Eternal October\"", ask: null, subject: { type: "delivery", id: "announcement-1#x#machines#g1" },
    subjectWords: "delivery announcement-1#x#machines#g1", raisedBy: "agent:announce", raisedAt: "2026-11-16T13:40:00Z", deadline: "2026-11-16T20:30:00Z", deadlineLocal: "3:30 PM",
    action: { kind: "answer", words: "Answer", requestId: "announce-draft-x-1", command: "papyrus reviews answer --id announce-draft-x-1 --decision approve|reject" },
  },
  {
    kind: "review", id: "rr-ratings-2026-11-16", mode: "soft_review", modeWords: "Soft review", mark: "?",
    reason: "3 ratings suggested, 1 five-star candidate", ask: null, subject: { type: "batch", id: "ratings-2026-11-16" },
    subjectWords: "batch ratings-2026-11-16", raisedBy: "agent:rate", raisedAt: "2026-11-16T12:00:00Z", deadline: null, deadlineLocal: null,
    action: { kind: "answer", words: "Answer", requestId: "rr-ratings-2026-11-16", command: "papyrus reviews answer --id rr-ratings-2026-11-16 --decision approve|reject" },
  },
];

const attention: TodayAttentionEntry[] = [
  {
    kind: "run", id: "run-t3", outcome: "unknown", mark: "!", words: "Outcome unknown", reason: "interrupted", title: "Translate", automationId: null, procedureKey: "translate_story",
    subject: { type: "story", id: "eternal-october" }, subjectWords: "story eternal-october", neededAt: "2026-11-16T14:30:00Z", neededLocal: "9:30 AM", error: null,
    action: { kind: "settle", words: "Settle", runId: "run-t3", command: "papyrus automations acknowledge --run run-t3",
              note: "Look at what it wrote, then settle it: the run leaves this list and stays in the history as Outcome unknown." },
  },
  {
    kind: "run", id: "run-t2", outcome: "failed", mark: "✗", words: "Failed", reason: "timed_out", title: "Translate", automationId: null, procedureKey: "translate_story",
    subject: null, subjectWords: null, neededAt: "2026-11-16T13:44:00Z", neededLocal: "8:44 AM", error: "timed out after 840 s",
    action: { kind: "acknowledge", words: "Acknowledge", runId: "run-t2", command: "papyrus automations acknowledge --run run-t2", note: null },
  },
  {
    ...overdueDelivery, kind: "overdue", record: "Delivery", dueLocal: "6:00 AM",
    action: { kind: "wake_now", words: "Wake now", available: true, note: "Wake now sends this record's own timer wake again, with the same key, so it runs once.",
              command: "papyrus agents wake-overdue --record Delivery --id announcement-daily#email#site#g1 --reason TEXT" },
  },
];

const due: TodayDue[] = [
  { kind: "schedule", what: "schedule", words: "Scheduled wake", at: "2026-11-16T11:00:00Z", local: "6:00 AM", title: "Daily summary", id: "newsletter.daily", detail: "0 6 * * * in America/New_York" },
  { kind: "story", what: "scheduledPublishAt", words: "Publishes", at: "2026-11-16T19:00:00Z", local: "2:00 PM", title: "Eternal October", id: "eternal-october", detail: null },
  { kind: "delivery", what: "lockAt", words: "Locks", at: "2026-11-16T20:30:00Z", local: "3:30 PM", title: "x machines", id: "announcement-1#x#machines#g1", detail: "not yet approved" },
  { kind: "review", what: "deadline", words: "Review deadline: goes on without review", at: "2026-11-16T20:30:00Z", local: "3:30 PM", title: "X announcement draft for \"Eternal October\"", id: "announce-draft-x-1", detail: null },
  { kind: "delivery", what: "releaseAt", words: "Goes out", at: "2026-11-16T21:00:00Z", local: "4:00 PM", title: "x machines", id: "announcement-1#x#machines#g1", detail: null },
];

/** A realistic Today for tests and the `?demo=1` newsroom. */
export const FIXTURE_TODAY: TodayOverview = {
  state: "ready", asOf: "2026-11-16T17:00:00.000Z", day: "2026-11-16", timeZone: "America/New_York", timeZoneSource: "site", timeZoneNote: null,
  start: "2026-11-16T05:00:00.000Z", end: "2026-11-17T05:00:00.000Z",
  waiting, attention, due,
  overdue: [overdueDelivery],
  rows: [announce, rate, translate],
  didNotRun: [
    { automationId: "digest.weekly", title: "Weekly digest", state: "Did not run", whyCode: "disabled", why: "Disabled: the router starts nothing for a disabled automation" },
    { automationId: "newsletter.daily", title: "Daily summary", state: "Did not run", whyCode: "no_wake", why: "Nothing woke it today" },
  ],
  sends: [
    {
      deliveryId: "announcement-weekly#email#site#g1", announcementId: "announcement-weekly", kind: "roundup", releasedAt: "2026-11-16T13:00:00Z", lists: ["weekly"], items: 5,
      state: "sent", stateShown: "✓ Sent", stateWords: "Sent", attempts: 1, lastAttempt: "sent",
      counts: { queued: 0, sent: 12, failed: 0, suppressed: 1, skipped: 2, delivered: 11, bounced: 1, complained: 0 }, countsText: "12 sent, 1 suppressed, 2 skipped, 11 delivered, 1 bounced", cost: null,
    },
  ],
  totals: { runs: 15, counts: { ...none, acted: 8, nothing: 4, asked: 1, failed: 1, unknown: 1 }, costUsd: 0.43, costKnownRuns: 14, costUnknownRuns: 1 },
};
