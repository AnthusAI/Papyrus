/**
 * Editorial checks: the Humanus result shapes the newsroom uses, and pure helpers
 * over them. Humanus counts offsets in UTF-16 code units, which is exactly how
 * JavaScript indexes strings, so spans apply to the body text as they are.
 */

export type Span = { start: number; end: number };
export type Severity = "info" | "warn" | "error";

export type EditorialFinding = {
  id: string;
  policyId: string;
  policyVersion: number;
  detectorId: string;
  lane: "rules" | "classifier";
  severity: Severity;
  status: "violation" | "review";
  segmentId: string;
  span: Span;
  excerpt: string;
  /** The excerpt as a reader sees it (inline markup removed). */
  excerptText?: string;
  message: string;
  probability?: number;
  rawProbability?: number;
  replacement?: string;
};

export type EditorialSegment = {
  id: string;
  kind: "document" | "paragraph" | "sentence";
  block?: "paragraph" | "heading" | "listItem";
  parentId?: string;
  start: number;
  end: number;
  textHash: string;
  /** Plain prose of a paragraph or sentence segment. */
  text?: string;
};

export type LaneStatus = { status: "ran" | "disabled" | "unavailable" | "failed" | "partial"; reason?: string; detectors?: number };

export type EditorialCheckResult = {
  schemaVersion: 1;
  offsetUnit: "utf16";
  document: { hash: string; length: number };
  pack: { packId: string; version: string };
  segments: EditorialSegment[];
  protected: { kind: string; start: number; end: number }[];
  findings: EditorialFinding[];
  coverage: unknown[];
  lanes: { rules: LaneStatus; classifier: LaneStatus };
  usage?: Record<string, number>;
};

export type RewriteOption = {
  id: string;
  span: Span;
  replacement: string;
  rationale: string;
  factVerificationRequired: boolean;
  unresolvedQuestions: string[];
};

export type RewriteResult = {
  target: { findingId?: string; span: Span; excerpt: string };
  model: string;
  options: RewriteOption[];
  dropped?: { replacement: string; reason: string }[];
};

export type FeedbackDecision = "accepted" | "fixed" | "dismissed";

export type EditorialFeedbackInput = {
  itemId: string;
  findingId: string;
  policyId: string;
  detectorId: string;
  lane: EditorialFinding["lane"];
  probability: number | null;
  decision: FeedbackDecision;
  reason: string | null;
  text: string | null;
};

/** Decisions on an article that has never been saved are kept under this id. */
export const UNSAVED_ITEM_ID = "unsaved";

const SEVERITY_ORDER: Record<Severity, number> = { error: 0, warn: 1, info: 2 };

/** Findings worth showing: not dismissed, not covering the whole document, most severe first, then in reading order. */
export function visibleFindings(findings: EditorialFinding[], dismissed: ReadonlySet<string>): EditorialFinding[] {
  return findings
    .filter((finding) => !dismissed.has(finding.id))
    .sort(
      (a, b) =>
        SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
        a.span.start - b.span.start ||
        a.policyId.localeCompare(b.policyId),
    );
}

/** Findings that can be marked in the text (document-level ones have no excerpt). */
export function inlineFindings(findings: EditorialFinding[]): EditorialFinding[] {
  return findings.filter((finding) => finding.excerpt.length > 0 && finding.span.end > finding.span.start);
}

export type FindingGroup = { policyId: string; severity: Severity; findings: EditorialFinding[] };

export function groupByPolicy(findings: EditorialFinding[]): FindingGroup[] {
  const groups = new Map<string, FindingGroup>();
  for (const finding of findings) {
    const group = groups.get(finding.policyId) ?? { policyId: finding.policyId, severity: finding.severity, findings: [] };
    group.findings.push(finding);
    if (SEVERITY_ORDER[finding.severity] < SEVERITY_ORDER[group.severity]) group.severity = finding.severity;
    groups.set(finding.policyId, group);
  }
  return [...groups.values()].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || a.policyId.localeCompare(b.policyId));
}

/** Open findings that should make an editor pause before publishing (never a block). */
export function publishWarnings(findings: EditorialFinding[], dismissed: ReadonlySet<string>): EditorialFinding[] {
  return visibleFindings(findings, dismissed).filter((finding) => finding.severity !== "info" && finding.status === "violation");
}

/** The text of the segment a finding sits in, which becomes a few-shot example for the classifier. */
export function findingSegmentText(result: EditorialCheckResult, body: string, finding: EditorialFinding): string | null {
  const segment = result.segments.find((candidate) => candidate.id === finding.segmentId);
  if (!segment || segment.kind === "document") return null;
  return body.slice(segment.start, segment.end);
}

export function feedbackFor(
  result: EditorialCheckResult,
  body: string,
  finding: EditorialFinding,
  decision: FeedbackDecision,
  itemId: string | null,
  reason: string | null = null,
): EditorialFeedbackInput {
  return {
    itemId: itemId ?? UNSAVED_ITEM_ID,
    findingId: finding.id,
    policyId: finding.policyId,
    detectorId: finding.detectorId,
    lane: finding.lane,
    probability: finding.rawProbability ?? finding.probability ?? null,
    decision,
    reason: reason?.trim() ? reason.trim() : null,
    text: finding.lane === "classifier" ? findingSegmentText(result, body, finding) : null,
  };
}

/** Replace one span of the body; the span must still hold the text it was computed for. */
export function applyReplacement(body: string, span: Span, expected: string, replacement: string): string | null {
  if (body.slice(span.start, span.end) !== expected) return null;
  return body.slice(0, span.start) + replacement + body.slice(span.end);
}

export function describeProbability(finding: EditorialFinding): string | null {
  if (finding.probability === undefined) return null;
  return `${Math.round(finding.probability * 100)}% sure`;
}

export function laneNotice(result: EditorialCheckResult): string | null {
  const classifier = result.lanes.classifier;
  if (classifier.status === "partial") return `Some sentences were not judged: ${classifier.reason ?? "the check ran out of time"}.`;
  if (classifier.status === "failed") return `The judgment checks failed: ${classifier.reason ?? "unknown error"}. Rule checks still ran.`;
  if (classifier.status === "unavailable" && (classifier.detectors ?? 0) === 0 && classifier.reason) return `Judgment checks are not configured: ${classifier.reason}.`;
  return null;
}
