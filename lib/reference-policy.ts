import type { MessageRecord, ReferenceRecord } from "./category-repository";

export const REFERENCE_CURATION_STATUSES = ["pending", "accepted", "rejected", "archived"] as const;
export type ReferenceCurationStatus = typeof REFERENCE_CURATION_STATUSES[number];

export const REFERENCE_REJECTION_REASON_CODES = [
  "out_of_scope",
  "policy_exclusion",
  "duplicate",
  "low_quality",
  "unavailable",
  "provenance",
  "other",
] as const;
export type ReferenceRejectionReasonCode = typeof REFERENCE_REJECTION_REASON_CODES[number];

const REFERENCE_REJECTION_REASON_CODE_SET = new Set<string>(REFERENCE_REJECTION_REASON_CODES);
const SCOPE_TRAINING_NEGATIVE_REASON_CODE_SET = new Set<string>(["out_of_scope", "policy_exclusion"]);

/** Rejection reasons that say the source is not relevant (scope-training negatives). */
export function isScopeTrainingNegativeReason(code: string): boolean {
  return SCOPE_TRAINING_NEGATIVE_REASON_CODE_SET.has(code);
}

/**
 * The phrases an editor writes when they mean one reason code and little else.
 *
 * The order matters, and the two scope-training codes come LAST: a sentence
 * that also names a mechanical reason ("already have it, and off our beat") is
 * filed under that reason instead. A false scope negative teaches the relevance
 * classifier something wrong; a missed one only leaves it untaught.
 *
 * Each phrase is a whole word or wording, never a fragment, so "slopes" is not
 * read as "slop". Words that say none of this yield no code at all rather than
 * the nearest guess.
 */
const WRITTEN_REASON_PHRASES: ReadonlyArray<readonly [ReferenceRejectionReasonCode, readonly string[]]> = [
  ["duplicate", [
    "duplicate", "duplicates", "duplicated", "duplication", "dupe", "reprint", "reprinted",
    "already have (it|this|that|the)", "already (got|covered|accepted|registered|ingested|indexed)",
    "already in (our|the) (corpus|list|feed|knowledge base|library)", "same (source|piece|story) as",
  ]],
  ["unavailable", [
    "paywall", "paywalled", "unavailable", "not available", "no longer (available|online|up|there|reachable)",
    "behind a (paywall|login|subscription|sign in)", "(dead|broken|404) link", "link is (dead|broken)",
    "(cannot|cant) (open|read|reach|access|download|retrieve)", "requires a (subscription|login|account|sign in)",
    "taken down", "timed out", "page is gone",
  ]],
  ["provenance", [
    "provenance", "unattributed", "unverified", "unverifiable", "untraceable",
    "(cannot|cant) (verify|attribute)", "no (byline|author|citation|attribution|provenance)",
    "(unknown|unclear|anonymous|missing) (author|source|origin|provenance)", "who wrote it",
  ]],
  ["low_quality", [
    "(low|poor) quality", "poorly (written|sourced|argued|researched|edited)", "badly written", "sloppy",
    "content farm", "clickbait", "seo (spam|bait|filler)", "slop", "junk", "spam", "no substance", "churnalism",
  ]],
  ["policy_exclusion", [
    "policy exclusion", "(our|house|editorial) policy", "against (our )?policy",
    "(policy|policies) (excludes?|forbids?|bars?|rules? out|says?)",
    "(excluded|barred|ruled out|forbidden) by (our )?policy",
    "we (dont|do not) (cover|run|publish|cite|take)", "not allowed", "disallowed", "prohibited",
    "blocklist", "blocklisted", "blocked source",
  ]],
  ["out_of_scope", [
    "out of scope", "outside (our|the) (scope|remit|coverage|beat|lane)", "not (in|within) (our|the) scope",
    "off topic", "nothing to do with", "not (our|the) (beat|subject|topic|area|coverage)",
    "not relevant", "no longer relevant", "irrelevant", "unrelated", "wrong (beat|subject|topic)",
  ]],
];

const WRITTEN_REASON_PATTERNS: ReadonlyArray<readonly [ReferenceRejectionReasonCode, RegExp]> =
  WRITTEN_REASON_PHRASES.map(([code, phrases]) => [code, new RegExp(`\\b(?:${phrases.join("|")})\\b`)] as const);

/**
 * The reason code a rejection is filed under when the editor gave none: what
 * their own words plainly say, else "other".
 *
 * Words are a reason — a written sentence is what the editor actually gives
 * now that there are no reason chips — but "other" is the honest answer for
 * words that name no policy code, rather than a guess the sentence cannot
 * support. Blank words are no reason at all, so this yields null and the
 * caller refuses the rejection.
 */
export function rejectionReasonCodeForWrittenReason(writtenReason: unknown): ReferenceRejectionReasonCode | null {
  const words = normalizeWrittenReason(writtenReason);
  if (!words) return null;
  for (const [code, pattern] of WRITTEN_REASON_PATTERNS) {
    if (pattern.test(words)) return code;
  }
  return "other";
}

/** Lower case, apostrophes dropped ("don't" -> "dont") and every other gap a single space, so phrases match plain prose. */
function normalizeWrittenReason(value: unknown): string {
  return String(value ?? "")
    .toLowerCase()
    .replace(/['\u2018\u2019]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function normalizeReferenceCurationStatus(value: unknown, defaultStatus: ReferenceCurationStatus = "pending"): ReferenceCurationStatus {
  const normalized = normalizePolicyToken(value ?? defaultStatus);
  if (normalized === "accepted" || normalized === "accept" || normalized === "ready" || normalized === "trusted") return "accepted";
  if (normalized === "rejected" || normalized === "reject" || normalized === "discarded") return "rejected";
  if (normalized === "archived" || normalized === "archive") return "archived";
  return "pending";
}

/** The curation actor the router writes when the Cyclotron accepts a confident, unvoted Reference on its own (src/papyrus_content/auto_accept.py). Not a person. */
export const AUTO_ACCEPT_ACTOR = "auto:cyclotron";

/** The actor for a Reference a monitor with a fixed delivery rule accepted on delivery: the rule match is the acceptance. */
export const AUTO_ACCEPT_RULE_ACTOR = "auto:rule";

/** True while a Reference stands accepted automatically, by the Cyclotron's confidence or by a monitor's rule. An editor's later Accept or Reject replaces the actor, so this is false from then on. */
export function isAutoAccepted(reference: { curationStatus?: unknown; curationStatusUpdatedBy?: unknown }): boolean {
  const actor = String(reference.curationStatusUpdatedBy ?? "").trim();
  return normalizeReferenceCurationStatus(reference.curationStatus) === "accepted" && (actor === AUTO_ACCEPT_ACTOR || actor === AUTO_ACCEPT_RULE_ACTOR);
}

export function referenceCurationStatusForAction(action: "accept" | "reject" | "reopen" | "archive"): ReferenceCurationStatus {
  if (action === "accept") return "accepted";
  if (action === "reject") return "rejected";
  if (action === "archive") return "archived";
  return "pending";
}

export function normalizeReferenceRejectionReasonCode(value: unknown): ReferenceRejectionReasonCode | null {
  const normalized = normalizePolicyToken(value);
  if (!normalized) return null;
  return REFERENCE_REJECTION_REASON_CODE_SET.has(normalized) ? normalized as ReferenceRejectionReasonCode : null;
}

export function isEvidenceEligibleReference(reference: Pick<ReferenceRecord, "versionState" | "curationStatus"> | null | undefined): boolean {
  return Boolean(reference)
    && reference?.versionState === "current"
    && normalizeReferenceCurationStatus(reference?.curationStatus) === "accepted";
}

export function referenceReasonCode(reference: Pick<ReferenceRecord, "metadata"> | null | undefined, messages: Array<Pick<MessageRecord, "metadata" | "createdAt">> = []): ReferenceRejectionReasonCode | null {
  const metadataReason = reasonCodeFromMetadata(reference?.metadata);
  if (metadataReason) return metadataReason;
  const sortedMessages = [...messages].sort((left, right) => String(right.createdAt ?? "").localeCompare(String(left.createdAt ?? "")));
  for (const message of sortedMessages) {
    const reason = reasonCodeFromMetadata(message.metadata);
    if (reason) return reason;
  }
  return null;
}

export function scopeTrainingLabelForReference(reference: Pick<ReferenceRecord, "versionState" | "curationStatus" | "metadata"> | null | undefined, messages: Array<Pick<MessageRecord, "metadata" | "createdAt">> = []): "positive" | "negative" | null {
  if (!reference || reference.versionState !== "current") return null;
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  if (status === "accepted") return "positive";
  if (status !== "rejected") return null;
  const reasonCode = referenceReasonCode(reference, messages);
  return reasonCode && SCOPE_TRAINING_NEGATIVE_REASON_CODE_SET.has(reasonCode) ? "negative" : null;
}

function reasonCodeFromMetadata(metadata: unknown): ReferenceRejectionReasonCode | null {
  const parsed = parseMetadataObject(metadata);
  return normalizeReferenceRejectionReasonCode(
    parsed.reasonCode
      ?? parsed.reason_code
      ?? parsed.curationReasonCode
      ?? parsed.curation_reason_code
      ?? parsed.rejectionReasonCode
      ?? parsed.rejection_reason_code,
  );
}

function parseMetadataObject(value: unknown): Record<string, unknown> {
  if (!value) return {};
  if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function normalizePolicyToken(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}
