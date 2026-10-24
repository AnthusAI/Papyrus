/** Shapes and wording for the newsroom Automation page. src/papyrus_content/automations.py produces them. */
import { formatUtc } from "./monitoring-overview";
import { getNewsroomNavHref } from "./newsroom-nav";

export { formatUtc };

export type AutomationUsage = {
  calls?: number;
  promptTokens?: number;
  completionTokens?: number;
  models?: Record<string, number>;
  complete?: boolean;
  unpricedModels?: string[];
};

export type AutomationRun = {
  origin: "monitor" | "manual" | "stage";
  /** The stage a story entered to start this run (origin "stage"). */
  stage?: string | null;
  requestedBy: string | null;
  reason: string | null;
  sourceId: string | null;
  referenceId: string | null;
  triggerStatus: string | null;
  runId: string | null;
  status: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  durationSeconds: number | null;
  error: string | null;
  runRecord: "found" | "missing" | "unavailable" | "none";
  storyId: string | null;
  /** False when no version of the story remains (it was deleted); null when this was not looked up. */
  storyExists?: boolean | null;
  /** Tool name to number of calls the procedure made, when the run recorded them. */
  toolsUsed?: Record<string, number> | null;
  storyVersionId: string | null;
  storyTitle: string | null;
  costUsd: number | null;
  costNote: string;
  budgetUsd: number | null;
  overBudget: boolean;
  usage: AutomationUsage | null;
};

/** A ProcedureRun of the same procedure that this automation did not start ("Started outside this automation"). */
export type AutomationOutsideRun = {
  runId: string | null;
  status: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  durationSeconds: number | null;
  error: string | null;
  requestedBy: string | null;
  storyId: string | null;
  storyVersionId: string | null;
  storyTitle: string | null;
  costUsd: number | null;
  costNote: string;
  overBudget: boolean;
};

export type AutomationRunNow = { available: boolean; reason: string | null; needsInput: boolean; inputNames: string[] };

export type AutomationLink = {
  state: "linked" | "input_differs" | "trigger_not_found" | "publication_not_in_router" | "router_not_found" | "not_applicable";
  text: string;
  routerMode?: string | null;
  routerEnabled?: boolean;
};

export type AutomationNotice = "monitoring_not_configured" | "monitoring_unavailable" | "other_publication" | "publication_not_routed" | "not yet supported";

export type AutomationRecord = {
  id: string;
  title: string;
  description: string | null;
  enabled: boolean;
  enabledNote: string;
  trigger: { kind: "monitor" | "schedule" | "event" | "manual"; config: Record<string, unknown> };
  /** Story-stage automations only: the stage that fires it, where the engine moves the story after, and the bot-hop limit. */
  onStage?: string | null;
  nextStage?: string | null;
  maxHops?: number | null;
  supported: boolean;
  supportNote: string | null;
  procedureKey: string;
  inputTemplate: Record<string, string>;
  limits: { timeoutSeconds?: number; maxConcurrent?: number; budgetUsdPerRun?: number };
  limitsNote: string;
  runNow: AutomationRunNow;
  createdAt: string | null;
  updatedAt: string | null;
  link: AutomationLink | null;
  runs: AutomationRun[];
  lastRun: AutomationRun | null;
  skippedAlreadyHadReference: number;
  notice: AutomationNotice | null;
  outsideRuns: AutomationOutsideRun[];
  outsideNotice: "outside_unavailable" | null;
};

export type AutomationOverview = {
  state: "ready" | "empty";
  asOf: string;
  monitoring: "ready" | "not_configured";
  automations: AutomationRecord[];
};

export type AutomationResult = AutomationOverview | { state: "unavailable" } | { error: "forbidden" | "bad_request" };

const KIND_WORDS: Record<string, string> = { monitor: "Monitor", schedule: "Schedule", event: "Event", manual: "Manual" };

export function triggerText(trigger: AutomationRecord["trigger"]): string {
  const kind = KIND_WORDS[trigger.kind] ?? trigger.kind;
  if (trigger.kind === "monitor") {
    return `${kind} ${String(trigger.config.monitorId ?? "?")}, delivering to ${String(trigger.config.publicationId ?? "?")}`;
  }
  if (trigger.kind === "event" && trigger.config.event === "story.stage_entered") {
    const next = trigger.config.nextStage ? `, then moves it to ${String(trigger.config.nextStage)}` : "";
    return `${kind}: a story enters ${String(trigger.config.onStage ?? "?")}${next}`;
  }
  return kind;
}

export const ENABLED_NOTE = "the router starts nothing for a disabled automation";

export function enabledText(record: Pick<AutomationRecord, "enabled">): string {
  return record.enabled ? "Enabled" : "Disabled";
}

const STATUS_WORDS: Record<string, string> = {
  completed: "Completed",
  failed: "Failed",
  running: "Running",
  starting: "Starting",
  started: "Started, no result recorded yet",
  startFailed: "Could not start",
  notRunnable: "Not runnable",
  notTriggered: "Not started",
  skipped: "Skipped",
  refused: "Refused",
  deferred: "Deferred, waiting for room",
};
const STATUS_MARKS: Record<string, string> = {
  completed: "✓", failed: "✕", startFailed: "✕", notRunnable: "✕", refused: "✕", skipped: "–", deferred: "…", started: "…", starting: "…", running: "…",
};

export function statusText(status: string | null | undefined): string {
  return status ? (STATUS_WORDS[status] ?? status) : "No runs";
}

export function statusMark(status: string | null | undefined): string {
  return status ? (STATUS_MARKS[status] ?? "") : "";
}

export function durationText(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "duration not recorded";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

export function dollars(value: number): string {
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

/** "Cost: $0.04 (estimated ...)" or "Cost: unknown (why)", with the advisory budget flagged in words. */
export function costText(run: Pick<AutomationRun, "costUsd" | "costNote" | "overBudget"> & { budgetUsd?: number | null }): string {
  const base = run.costUsd === null ? `Cost: unknown (${run.costNote})` : `Cost: ${dollars(run.costUsd)} (${run.costNote})`;
  return run.overBudget && run.budgetUsd != null ? `${base}. Over the budget of ${dollars(run.budgetUsd)} per run` : base;
}

export function toolsText(run: Pick<AutomationRun, "toolsUsed">): string {
  const tools = Object.entries(run.toolsUsed ?? {}).sort(([a], [b]) => a.localeCompare(b));
  return tools.length ? `Tools used: ${tools.map(([name, count]) => `${name} x${count}`).join(", ")}` : "Tools used: none recorded";
}

export function whoText(run: Pick<AutomationRun, "origin" | "requestedBy" | "sourceId"> & { stage?: string | null }): string {
  if (run.origin === "stage") return `Story entered ${run.stage ?? "a stage"}`;
  return run.origin === "manual" ? `Run now by ${run.requestedBy ?? "someone"}` : `Item: ${run.sourceId ?? "unknown"}`;
}

export const LIMITS_NOTE = "the timeout and the number at a time (when set) are enforced when a run starts; the budget is advisory and only flagged";

export function atATimeText(limits: { maxConcurrent?: number }): string {
  return limits.maxConcurrent === undefined ? "no limit on how many at a time" : `${limits.maxConcurrent} at a time`;
}

export type RunNowResult =
  | { state: "started"; automationId: string; requestedBy: string }
  | { state: "refused"; reason: string }
  | { state: "unavailable" }
  | { error: "forbidden" | "bad_request" };

export function runNowMessage(result: RunNowResult): string {
  if ("error" in result) return result.error === "forbidden" ? "Run now is for editors and admins." : "The request was not understood.";
  if (result.state === "started") return "Started. The run appears in the list below within a minute; the page refreshes by itself.";
  if (result.state === "refused") return `Not started: ${result.reason}`;
  return "Not started: the request could not be completed right now. Nothing was started.";
}

/** The input a person typed for Run now: a JSON object, or nothing (the record's own input is used). */
export function parseRunInput(text: string): { ok: true; value: Record<string, unknown> | null } | { ok: false; message: string } {
  if (!text.trim()) return { ok: true, value: null };
  try {
    const parsed = JSON.parse(text);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return { ok: false, message: "The input must be a JSON object, for example {\"name\": \"value\"}." };
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, message: "The input is not valid JSON." };
  }
}

/** A starting point for the input box: the record's input names with empty values. */
export function inputTemplateText(names: string[]): string {
  return JSON.stringify(Object.fromEntries(names.map((name) => [name, ""])), null, 2);
}

const LINK_WORDS: Record<AutomationLink["state"], string> = {
  linked: "Linked: the router's trigger matches this record.",
  input_differs: "Differs: the router's input template is not the same as this record's.",
  trigger_not_found: "Not linked: the router has no trigger for this procedure.",
  publication_not_in_router: "Not linked: the router does not deliver to this publication.",
  router_not_found: "Not linked: the monitor has no router configuration.",
  not_applicable: "Not yet supported",
};

export function linkText(link: AutomationLink | null): string {
  return link ? LINK_WORDS[link.state] ?? link.text : "Not checked";
}

const NOTICE_WORDS: Record<string, string> = {
  monitoring_not_configured: "Monitoring is not connected to this site's account, so run history cannot be shown.",
  monitoring_unavailable: "Run history could not be read right now. The record is shown without it.",
  other_publication: "This automation belongs to another publication, so its runs are not shown here.",
  publication_not_routed: "This publication is not one of the router's outputs, so there are no runs to show.",
  "not yet supported": "Only monitor automations run today. This one is stored but nothing starts it.",
};

export const OUTSIDE_NOTICE = "The procedure's other runs could not be read right now.";

export function noticeText(notice: AutomationNotice | null): string | null {
  return notice ? (NOTICE_WORDS[notice] ?? notice) : null;
}

export function storyHref(storyId: string, demo?: boolean): string {
  return getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(storyId)}`, demo);
}

export function proceduresHref(demo?: boolean): string {
  return getNewsroomNavHref("/newsroom/administration/procedures", demo);
}
