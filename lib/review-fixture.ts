import type { MonitoringEmailDetails, MonitoringEmailSummary } from "./monitoring-overview";
import type { ReviewRequest } from "./review-requests";

/** Demo and test data: one of each mode, a timed-out soft review, and an answered one whose steering was applied. */
export const FIXTURE_REVIEW_REQUESTS: ReviewRequest[] = [
  {
    id: "rr-hard-1", subject: { type: "story", id: "story-ruling-1" }, mode: "hard_gate", reason: "Accept this ruling summary before it is published",
    ask: "Check the holding and the quoted passages.", raisedBy: "distinctive.ttab.ruling-analysis", raisedAt: "2026-10-23T08:00:00Z", deadline: null,
    state: "open", answer: null, links: [], history: [{ at: "2026-10-23T08:00:00Z", event: "raised", by: "distinctive.ttab.ruling-analysis", note: "hard_gate" }],
    appliedIn: null, updatedAt: "2026-10-23T08:00:00Z",
  },
  {
    id: "rr-soft-2", subject: { type: "batch", id: "2026-W43" }, mode: "soft_review", reason: "3 new story ideas to review",
    ask: "Move an idea forward to accept it, or move it to Spiked with a reason to decline it.", raisedBy: "idea-pipeline", raisedAt: "2026-10-23T07:00:00Z",
    deadline: null, state: "open", answer: null,
    links: [{ type: "story", id: "idea-1", label: "story idea 1" }, { type: "story", id: "idea-2", label: "story idea 2" }, { type: "story", id: "idea-3", label: "story idea 3" }],
    history: [], appliedIn: null, updatedAt: "2026-10-23T07:00:00Z",
  },
  {
    id: "rr-soft-1", subject: { type: "story", id: "story-trend-1" }, mode: "soft_review", reason: "A trend story is ready for a second look",
    ask: null, raisedBy: "trend-pipeline", raisedAt: "2026-10-22T07:00:00Z", deadline: "2026-10-25T07:00:00Z", state: "open", answer: null,
    links: [], history: [], appliedIn: null, updatedAt: "2026-10-22T07:00:00Z",
  },
  {
    id: "rr-flag-1", subject: { type: "reference", id: "ref-1" }, mode: "flag", reason: "Two sources disagree about the filing date",
    ask: null, raisedBy: "reference-intake", raisedAt: "2026-10-22T10:00:00Z", deadline: null, state: "open", answer: null, links: [], history: [],
    appliedIn: null, updatedAt: "2026-10-22T10:00:00Z",
  },
  {
    id: "rr-late-1", subject: { type: "story", id: "story-old" }, mode: "soft_review", reason: "Check the headline", ask: null, raisedBy: "copy-editor",
    raisedAt: "2026-10-10T07:00:00Z", deadline: "2026-10-17T07:00:00Z", state: "timed_out", answer: null, links: [],
    history: [{ at: "2026-10-17T07:00:00Z", event: "timed_out", by: "system", note: "proceeded without review" }], appliedIn: null, updatedAt: "2026-10-17T07:00:00Z",
  },
  {
    id: "rr-done-1", subject: { type: "batch", id: "2026-W42" }, mode: "soft_review", reason: "4 new story ideas to review", ask: null, raisedBy: "idea-pipeline",
    raisedAt: "2026-10-16T07:00:00Z", deadline: "2026-10-23T07:00:00Z", state: "answered",
    answer: { decision: "feedback", feedback: "Fewer listicles", steer: "not_this_kind", by: "Ed Itor", at: "2026-10-17T09:00:00Z" },
    links: [], history: [], appliedIn: { runId: "run-w43", by: "idea-pipeline", at: "2026-10-20T07:00:00Z" }, updatedAt: "2026-10-17T09:00:00Z",
  },
  {
    id: "rr-done-2", subject: { type: "proposal", id: "proposal-4" }, mode: "soft_review", reason: "A concept rename was proposed", ask: null, raisedBy: "concept-bot",
    raisedAt: "2026-10-18T07:00:00Z", deadline: "2026-10-25T07:00:00Z", state: "answered",
    answer: { decision: "feedback", feedback: "Keep the old name for sports", steer: "adjust", by: "Ed Itor", at: "2026-10-19T09:00:00Z" },
    links: [], history: [], appliedIn: null, updatedAt: "2026-10-19T09:00:00Z",
  },
  {
    id: "rr-soft-3", subject: { type: "story", id: "story-weekly" }, mode: "soft_review", reason: "Check the tone of the weekly summary", ask: "Is the tone right for readers?",
    raisedBy: "copy-editor", raisedAt: "2026-10-23T06:00:00Z", deadline: "2026-10-31T07:00:00Z", state: "open", answer: null, links: [], history: [], appliedIn: null,
    updatedAt: "2026-10-23T06:00:00Z",
  },
];

/** Demo and test ideas for the batch fixture: generated story ideas, by lineage id, with the stage each is in (two wait in the Idea column, one was already spiked). */
export type FixtureIdea = { id: string; title: string; stage: string };
export const FIXTURE_IDEAS: FixtureIdea[] = [
  { id: "idea-1", title: "Sparse attention goes open", stage: "idea" },
  { id: "idea-2", title: "A new quantisation paper challenges 4-bit defaults", stage: "idea" },
  { id: "idea-3", title: "Eight new models this week", stage: "spiked" },
];

/** Demo and test data: email submissions held for review (placeholders only, no real addresses). */
export const FIXTURE_HELD_EMAILS: MonitoringEmailSummary[] = [
  {
    receiptId: "receipt-held-1", observedAt: "2026-10-26T15:20:00Z", status: "held", subject: "Interesting preprint on retrieval for legal research",
    envelopeSender: "bounce@mailer.example.test", headerFrom: "A Reader <reader@example.test>", warnings: ["dkim_failed"],
    verdicts: { spf: "PASS", dkim: "FAIL", dmarc: "FAIL", spam: "PASS", virus: "PASS" }, linkCount: 2, processedCount: 0, unresolvedLinkCount: 0,
    reviewRequired: true, errorCode: null, quarantine: { state: "quarantined", decision: null, failure: null },
  },
];

export const FIXTURE_EMAIL_DETAILS: Record<string, MonitoringEmailDetails> = {
  "receipt-held-1": {
    submission: { ...FIXTURE_HELD_EMAILS[0], corpusId: null },
    safeBodyText: "Hi,\n\nThought you would want to see this preprint on retrieval-augmented drafting for legal research. The authors compare three retrievers on 4,000 rulings.\n\nhttps://example.org/papers/retrieval-legal\nhttps://example.org/papers/retrieval-legal/data\n\nBest,\nA Reader",
    candidateLinks: [{ url: "https://example.org/papers/retrieval-legal", title: "Retrieval for legal research" }, { url: "https://example.org/papers/retrieval-legal/data", title: "Dataset" }],
    sourceMaterialIsUntrusted: true,
  },
};
