import type { MonitoringEmailDetails, MonitoringEmailSummary } from "./monitoring-overview";
import type { DraftRow } from "./review-drafts";
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
    ask: "Accept or reject each draft.", raisedBy: "idea-pipeline", raisedAt: "2026-10-23T07:00:00Z",
    deadline: "2026-10-30T07:00:00Z", state: "open", answer: null,
    links: [{ type: "proposal", id: "proposal-1", label: "story idea 1" }, { type: "proposal", id: "proposal-2", label: "story idea 2" }, { type: "proposal", id: "proposal-3", label: "story idea 3" }],
    history: [], appliedIn: null, updatedAt: "2026-10-23T07:00:00Z",
  },
  {
    id: "rr-soft-1", subject: { type: "proposal", id: "proposal-9" }, mode: "soft_review", reason: "A trend story draft is ready",
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

const TREND_BODY = (dek: string, section: string) => [
  `${dek} [1][3]`, "", "## Signals cited", "",
  "1. Sparse attention: technique, 32 items in the last 2 weeks against 9 in the 6 weeks before (about 4 expected; p=0.001 after correcting for 40 windows tried) `entity:sparse-attention`",
  "2. Open weights: cluster, steady, 58 items `cluster:open-weights`", "", "## Sources", "",
  "3. A sparse-attention model ships open weights (2026-10-20) https://example.org/sparse-attention",
  "4. Benchmarks for long-context models (2026-10-18) https://example.org/long-context", "", `Section: ${section}. Drafted by AI from the knowledge snapshot; an editor approves the copy and the figure before anything is published.`, "",
].join("\n");

/** Demo and test drafts for the batch fixtures: a trend story, a monitor story and a draft that already has a decision. */
export const FIXTURE_DRAFTS: DraftRow[] = [
  {
    id: "proposal-1", kind: "story_draft", title: "Sparse attention goes open", summary: "Open-weight models are adopting sparse attention faster than closed labs reported.",
    body: TREND_BODY("Open-weight models are adopting sparse attention faster than closed labs reported.", "Research"), state: "draft", held: false,
    evidence: { signals: 2, source: "knowledge snapshot 2026-10-23 (shipped), papyrus ideas trends" }, history: [], createdAt: "2026-10-23T07:00:00Z",
  },
  {
    id: "proposal-2", kind: "story_draft", title: "A new quantisation paper challenges 4-bit defaults", summary: "A preprint argues that 3-bit weights match 4-bit accuracy on long-context tasks.",
    body: ["A preprint argues that 3-bit weights match 4-bit accuracy on long-context tasks. [1]", "", "## Source", "", "1. Rethinking 4-bit defaults (2026-10-22) https://example.org/quantisation", "",
      "Section: Research. Drafted by AI from an item the arxiv-cs monitor found. An editor approves the copy before anything is published.", ""].join("\n"),
    state: "draft", held: false, evidence: { signals: 1, source: "arxiv-cs monitor: https://example.org/quantisation" }, history: [], createdAt: "2026-10-23T07:00:00Z",
  },
  {
    id: "proposal-3", kind: "story_draft", title: "Eight new models this week", summary: "A list of the week's releases.",
    body: TREND_BODY("A list of the week's releases.", "News"), state: "editor_review", held: false,
    evidence: { signals: 2, source: "knowledge snapshot 2026-10-23 (shipped), papyrus ideas trends" }, history: [], createdAt: "2026-10-23T07:00:00Z",
  },
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
