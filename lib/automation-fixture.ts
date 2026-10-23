import type { AutomationOverview, AutomationRun } from "./automation-overview";

const NOT_RECORDED = "not recorded for this run";
const ESTIMATED = "estimated from the model usage reported by the run";

function run(fields: Partial<AutomationRun> & Pick<AutomationRun, "status" | "startedAt">): AutomationRun {
  return {
    origin: "monitor", requestedBy: null, reason: null, sourceId: null, referenceId: null, triggerStatus: fields.status, runId: null,
    finishedAt: null, durationSeconds: null, error: null, runRecord: "none", storyId: null, storyVersionId: null, storyTitle: null,
    costUsd: null, costNote: NOT_RECORDED, budgetUsd: null, overBudget: false, usage: null, ...fields,
  };
}

/** A realistic overview for tests and the `?demo=1` newsroom: one live monitor automation and one stored schedule. */
export const FIXTURE_AUTOMATION_OVERVIEW: AutomationOverview = {
  state: "ready",
  asOf: "2026-10-23T12:00:00Z",
  monitoring: "ready",
  automations: [
    {
      id: "example.ttab.ruling-analysis",
      title: "Analyze new TTAB rulings",
      description: "Drafts a story for each new Board decision.",
      enabled: true,
      enabledNote: "the router starts nothing for a disabled automation",
      trigger: { kind: "monitor", config: { monitorId: "ttab", publicationId: "example" } },
      supported: true,
      supportNote: null,
      procedureKey: "example.ttab.ruling-analysis",
      inputTemplate: { proceeding: "{sourceIdPrefix}", opinion_url: "{documentUrl}" },
      limits: { timeoutSeconds: 840, maxConcurrent: 1, budgetUsdPerRun: 0.05 },
      limitsNote: "the timeout and the number at a time are enforced when a run starts; the budget is advisory and only flagged",
      runNow: { available: true, reason: null, needsInput: true, inputNames: ["opinion_url", "proceeding"] },
      createdAt: "2026-10-23T10:00:00Z",
      updatedAt: "2026-10-23T10:00:00Z",
      link: { state: "linked", text: "The router's trigger matches this record.", routerMode: "live", routerEnabled: true },
      notice: null,
      skippedAlreadyHadReference: 2,
      lastRun: null,
      runs: [
        run({ sourceId: "91000001-EXA_26", referenceId: "ref-1", runId: "run-1", status: "completed", triggerStatus: "completed",
              startedAt: "2026-10-23T11:30:00Z", finishedAt: "2026-10-23T11:33:10Z", durationSeconds: 190, runRecord: "found",
              storyId: "story-1", storyVersionId: "version-1", storyTitle: "Board affirms a refusal for likelihood of confusion",
              costUsd: 0.0123, costNote: ESTIMATED, budgetUsd: 0.05,
              usage: { calls: 4, promptTokens: 61000, completionTokens: 5200, models: { "gpt-6-luna": 4 }, complete: true, unpricedModels: [] } }),
        run({ sourceId: "91000002-EXA_26", referenceId: "ref-2", runId: "run-2", status: "failed", triggerStatus: "failed",
              startedAt: "2026-10-23T05:30:00Z", finishedAt: "2026-10-23T05:31:00Z", durationSeconds: 60, runRecord: "found",
              error: "the opinion could not be downloaded" }),
        run({ sourceId: "91000003-EXA_26", referenceId: "ref-3", status: "started", startedAt: "2026-10-23T11:59:00Z" }),
        run({ origin: "manual", requestedBy: "ryan@example.test", runId: "run-4", status: "completed", triggerStatus: "completed",
              startedAt: "2026-10-23T09:00:00Z", finishedAt: "2026-10-23T09:05:00Z", durationSeconds: 300, runRecord: "found",
              costUsd: 0.081, costNote: ESTIMATED, budgetUsd: 0.05, overBudget: true }),
        run({ sourceId: "91000005-EXA_26", referenceId: "ref-5", status: "refused", startedAt: "2026-10-23T08:00:00Z",
              reason: "automation at its limit: 1 running, at most 1 at a time" }),
        run({ sourceId: "91000006-EXA_26", referenceId: "ref-6", status: "skipped", startedAt: "2026-10-22T08:00:00Z",
              reason: "automation disabled" }),
      ],
      outsideRuns: [
        { runId: "run-9", status: "completed", startedAt: "2026-10-22T15:00:00Z", finishedAt: "2026-10-22T15:02:00Z", durationSeconds: 120,
          error: null, requestedBy: "papyrus-cli", storyId: null, storyVersionId: null, storyTitle: null, costUsd: null,
          costNote: NOT_RECORDED, overBudget: false },
      ],
      outsideNotice: null,
    },
    {
      id: "example.weekly-digest",
      title: "Weekly digest",
      description: null,
      enabled: false,
      enabledNote: "the router starts nothing for a disabled automation",
      trigger: { kind: "schedule", config: { cron: "0 9 * * 1" } },
      supported: false,
      supportNote: "not yet supported",
      procedureKey: "example.weekly-digest",
      inputTemplate: {},
      limits: { timeoutSeconds: 840, maxConcurrent: 1 },
      limitsNote: "the timeout and the number at a time are enforced when a run starts; the budget is advisory and only flagged",
      runNow: { available: false, reason: "not yet supported", needsInput: false, inputNames: [] },
      createdAt: "2026-10-23T10:05:00Z",
      updatedAt: "2026-10-23T10:05:00Z",
      link: { state: "not_applicable", text: "not yet supported" },
      notice: "not yet supported",
      skippedAlreadyHadReference: 0,
      lastRun: null,
      runs: [],
      outsideRuns: [],
      outsideNotice: null,
    },
  ],
};
// Newest first, as the history is served.
FIXTURE_AUTOMATION_OVERVIEW.automations[0].runs.sort((left, right) => String(right.startedAt).localeCompare(String(left.startedAt)));
FIXTURE_AUTOMATION_OVERVIEW.automations[0].lastRun = FIXTURE_AUTOMATION_OVERVIEW.automations[0].runs[0];
