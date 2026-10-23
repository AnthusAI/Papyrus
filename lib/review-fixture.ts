import type { ReviewRequest } from "./review-requests";

/** Demo and test data: one of each mode, a timed-out soft review, and an answered one whose steering was applied. */
export const FIXTURE_REVIEW_REQUESTS: ReviewRequest[] = [
  {
    id: "rr-hard-1", subject: { type: "story", id: "story-ruling-1" }, mode: "hard_gate", reason: "Approve this ruling summary before it is published",
    ask: "Check the holding and the quoted passages.", raisedBy: "distinctive.ttab.ruling-analysis", raisedAt: "2026-10-23T08:00:00Z", deadline: null,
    state: "open", answer: null, links: [], history: [{ at: "2026-10-23T08:00:00Z", event: "raised", by: "distinctive.ttab.ruling-analysis", note: "hard_gate" }],
    appliedIn: null, updatedAt: "2026-10-23T08:00:00Z",
  },
  {
    id: "rr-soft-2", subject: { type: "batch", id: "2026-W43" }, mode: "soft_review", reason: "3 new story ideas to review",
    ask: "Approve to keep them all, reject to drop the batch, or steer with a note.", raisedBy: "idea-pipeline", raisedAt: "2026-10-23T07:00:00Z",
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
];
