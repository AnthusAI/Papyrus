/** Shapes and wording for the newsroom Monitoring page. The function in src/papyrus_content/monitoring_view.py produces them. */
import { getNewsroomNavHref } from "./newsroom-nav";

export type MonitoringDeliveryState = "delivered" | "failed" | "pending" | "not_applicable" | null;

export type MonitoringRelevance = {
  publicationId: string;
  site: string | null;
  relevant: boolean | null;
  label: string | null;
  confidence: number | null;
  delivery: {
    state: MonitoringDeliveryState;
    referenceId?: string | null;
    referenceLineageId?: string | null;
    deliveredAt?: string | null;
    error?: string | null;
    attempts?: number | null;
  };
};

export type MonitoringItem = {
  monitorId?: string;
  sourceId: string;
  revision: number;
  title: string;
  url: string | null;
  discussionUrl: string | null;
  observedAt: string | null;
  routing: string;
  routingNote: string | null;
  decidedAt: string | null;
  relevance: MonitoringRelevance[];
};

export type MonitoringEmailSummary = {
  receiptId: string; observedAt: string | null; status: string; subject: string | null;
  envelopeSender: string | null; headerFrom: string | null; warnings: string[];
  verdicts: Record<string, string>; linkCount: number; processedCount: number; unresolvedLinkCount: number;
  reviewRequired: boolean; errorCode: string | null;
};

export type MonitoringEmailDetails = {
  submission: MonitoringEmailSummary & { corpusId: string | null }; safeBodyText: string;
  candidateLinks: { url: string; title: string; resolutionStatus?: "unresolved" }[]; sourceMaterialIsUntrusted: true;
} | { error: "forbidden" | "bad_request" } | { state: "unavailable" | "not_configured" };

export type MonitoringEmailArticleResolution = {
  url: string; title: string; resolved: true;
} | { error: "forbidden" | "bad_request" | "not_resolvable" | "resolution_failed"; reason?: string } | { state: "unavailable" };

export type EmailReferenceImportItem = { candidateIndex: number; source_uri: string };
export type EmailReferenceImportOutcome = {
  imported: number; references: { id: string; lineageId: string; curationStatus: string }[]; error?: string;
};

/** Split a complete editor selection into API work batches; the batch size is not a total link limit. */
export function emailReferenceBatches<T>(items: T[], batchSize = 20): T[][] {
  if (!Number.isSafeInteger(batchSize) || batchSize < 1) throw new Error("batchSize must be a positive integer");
  const batches: T[][] = [];
  for (let offset = 0; offset < items.length; offset += batchSize) {
    batches.push(items.slice(offset, offset + batchSize));
  }
  return batches;
}

/** Async email actions may only update the receipt that is still open. */
export function isCurrentEmailSubmissionAction(activeReceiptId: string | null, actionReceiptId: string): boolean {
  return activeReceiptId === actionReceiptId;
}

export function beginEmailSubmissionAction(inFlight: Set<string>, actionKey: string): boolean {
  if (inFlight.has(actionKey)) return false;
  inFlight.add(actionKey);
  return true;
}

export function endEmailSubmissionAction(inFlight: Set<string>, actionKey: string): void {
  inFlight.delete(actionKey);
}

export type MonitoringRun = {
  runId: string;
  startedAt: string;
  status: string;
  new: number;
  revised: number;
  unchanged: number;
  itemCount: number | null;
  errorCount: number;
  errors: (string | null)[];
};

export type MonitoringRouterRun = {
  runId: string;
  startedAt: string;
  mode: string;
  status: string;
  stoppedBy: string | null;
  waitingForClassifier?: string[];
  counts: Record<string, number>;
  errorCount: number;
};

export type MonitoringFeed = {
  id: string;
  sourceUrl: string | null;
  intervalSeconds: number | null;
  enabled: boolean;
  lastStatus: string | null;
  lastFinishedAt: string | null;
  nextDueAt: string | null;
};

export type MonitoringOverview = {
  state: "ready" | "empty";
  asOf: string;
  notice?: "publication_not_routed";
  scope: { mode: "publication" | "all"; publicationId: string | null; site: string | null; canViewAll: boolean };
  feeds: MonitoringFeed[];
  runs: MonitoringRun[];
  routerRuns: MonitoringRouterRun[];
  router: { mode: string; feedback: boolean; enabled: boolean } | null;
  usage: {
    day: string;
    decisionsToday: number;
    decisionsTotal: number;
    historyComplete: boolean;
  } | null;
  items: MonitoringItem[];
  /** Monitors that do not route to this site: named only, with no items. */
  otherMonitors?: string[];
  emailSubmissions?: MonitoringEmailSummary[];
  hiddenNotRelevant: number;
};

export type MonitoringResult =
  | MonitoringOverview
  | { state: "not_configured" }
  | { state: "unavailable" }
  | { error: "forbidden" | "bad_request" };

const ROUTING_WORDS: Record<string, string> = {
  collected: "Collected, waiting for the router",
  "dry-run-validated": "Checked in a dry run, not sent",
  decided: "Judged, delivery not finished",
  routed: "Routed",
  refused: "Refused by the shared Cyclotron",
  uncertain: "Uncertain, needs a person",
  error: "Error",
};

export function routingLabel(routing: string): string {
  return ROUTING_WORDS[routing] ?? routing;
}

/** Fixed-format UTC time so the page reads the same everywhere. */
export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "never";
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso);
  return match ? `${match[1]} ${match[2]} UTC` : iso;
}

export function confidenceText(confidence: number | null): string {
  return confidence === null ? "confidence not reported" : `${Math.round(confidence * 100)}% confidence`;
}

export function everyText(seconds: number | null): string {
  if (!seconds) return "on a schedule";
  return seconds % 3600 === 0 ? `every ${seconds / 3600} h` : seconds % 60 === 0 ? `every ${seconds / 60} min` : `every ${seconds} s`;
}

export function referenceHref(lineageId: string, demo?: boolean): string {
  return getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(lineageId)}`, demo);
}

export function describeRelevance(entry: MonitoringRelevance): string {
  if (entry.relevant === null) return "Not judged yet";
  return entry.relevant ? "Relevant" : "Not relevant";
}

export function describeDelivery(entry: MonitoringRelevance): string {
  switch (entry.delivery.state) {
    case "delivered": return "In the References queue";
    case "failed": return "Not in the References queue: delivery failed";
    case "pending": return "Not in the References queue yet";
    case "not_applicable": return "Nothing to deliver";
    default: return "";
  }
}
