/** Shapes and wording for the newsroom Automation page. src/papyrus_content/automations.py produces them. */
import { formatUtc } from "./monitoring-overview";
import { getNewsroomNavHref } from "./newsroom-nav";

export { formatUtc };

export type AutomationRun = {
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
  storyVersionId: string | null;
  storyTitle: string | null;
  costUsd: number | null;
  costNote: string;
};

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
  supported: boolean;
  supportNote: string | null;
  procedureKey: string;
  inputTemplate: Record<string, string>;
  limits: { timeoutSeconds?: number; maxConcurrent?: number; budgetUsdPerRun?: number };
  limitsNote: string;
  createdAt: string | null;
  updatedAt: string | null;
  link: AutomationLink | null;
  runs: AutomationRun[];
  lastRun: AutomationRun | null;
  skippedAlreadyHadReference: number;
  notice: AutomationNotice | null;
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
  return kind;
}

export const ENABLED_NOTE = "display only until the router honours it";

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
};
const STATUS_MARKS: Record<string, string> = { completed: "✓", failed: "✕", startFailed: "✕", notRunnable: "✕", started: "…", starting: "…", running: "…" };

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

export function noticeText(notice: AutomationNotice | null): string | null {
  return notice ? (NOTICE_WORDS[notice] ?? notice) : null;
}

export function storyHref(storyId: string, demo?: boolean): string {
  return getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(storyId)}`, demo);
}

export function proceduresHref(demo?: boolean): string {
  return getNewsroomNavHref("/newsroom/administration/procedures", demo);
}
