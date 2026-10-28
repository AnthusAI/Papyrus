"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import type { EmailDecisionResult, MonitoringEmailDetails, MonitoringEmailSummary } from "../lib/monitoring-overview";
import { proposalReceiptMessage, stateLabel, type ProposalReceipt } from "../lib/proposals-admin";
import type { DraftLoad, ReviewLoad } from "../lib/review-client";
import { acceptPath, batchAnswer, draftView, rejectPath, undecidedDraftIds, withDecision, draftDecisionUpdate, type DraftChoice, type DraftView } from "../lib/review-drafts";
import { previewsBySourceAddress, recentDecisions } from "../lib/notification-feed";
import { answerUpdate, cyclotronAutoDecided, draftIdsOf, isDraftReview, sectionReviews, type AnswerInput, type DraftDecision, type ReviewRequest } from "../lib/review-requests";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { learnFreshness } from "../lib/reference-feed-ranking";
import { learnConfidenceThreshold, shapingThisWeek } from "../lib/needs-me-ranking";
import { buildNeedsMeItems } from "../lib/needs-me-items";
import { captureStatusesByLineage } from "../lib/reference-capture";
import { normalizeReferenceCurationStatus, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import type { ReferencePreview } from "../lib/reference-preview";
import { referenceLineageId } from "../lib/newsroom-references";
import { loadNotificationSnapshot, saveNotificationSnapshot } from "../lib/reference-feed-cache";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { SITE_BRAND } from "../lib/site-brand";
import { FIXTURE_DRAFTS, FIXTURE_EMAIL_DETAILS, FIXTURE_HELD_EMAILS, FIXTURE_REVIEW_REQUESTS } from "../lib/review-fixture";
import { NeedsMeView, type NeedsMeDecision } from "./needs-me-feed";
import type { NeedsMeEntry } from "../lib/needs-me-items";
import type { CorrectCaptureAction } from "./reference-capture-client";
import type { ReviewChoice } from "./reference-review-card";

export type NotificationLoadState = "loading" | "ready" | "forbidden" | "unavailable";
export type DraftsLoadState = "loading" | "ready" | "failed";

/** What a real-data preview shows instead of the invented sample (scripts/export-notification-center-fixture.py). */
export type NotificationFixture = { requests: ReviewRequest[]; drafts: Parameters<typeof draftView>[0][]; emails?: MonitoringEmailSummary[] };

const NO_VISIT: ReadonlySet<string> = new Set();
const NO_PREVIEWS: ReadonlyMap<string, ReferencePreview> = new Map();
const NO_ATTACHMENTS: ReferenceAttachmentRecord[] = [];

/** Everything the container reads and writes. The live one talks to the site's data API; tests pass a fake. */
export type NotificationApi = {
  loadReviews: () => Promise<ReviewLoad>;
  loadDrafts: (ids: string[]) => Promise<DraftLoad>;
  loadStoryTitles: (ids: string[]) => Promise<{ titles: Record<string, string>; deleted: string[]; excerpts?: Record<string, string> }>;
  answerReviewRequest: (request: ReviewRequest, input: AnswerInput, by: string) => Promise<ReviewRequest>;
  saveDraftDecision: (request: ReviewRequest, draftId: string, decision: DraftDecision) => Promise<ReviewRequest>;
  markReviewRead: (userKey: string, requestId: string) => Promise<void>;
  transitionProposalPath: (proposalId: string, path: readonly string[]) => Promise<ProposalReceipt>;
  /** Email submissions held for review (Monitoring's own read). Optional: a site without monitoring has none. */
  loadHeldEmails?: () => Promise<MonitoringEmailSummary[]>;
  loadEmail?: (receiptId: string) => Promise<MonitoringEmailDetails>;
  decideEmail?: (receiptId: string, decision: "accept" | "reject", reason: string) => Promise<EmailDecisionResult>;
};

const liveApi: NotificationApi = {
  loadReviews: async () => (await import("../lib/review-client")).loadReviews(),
  loadDrafts: async (ids) => (await import("../lib/review-client")).loadDrafts(ids),
  loadStoryTitles: async (ids) => (await import("../lib/review-client")).loadStoryTitles(ids),
  answerReviewRequest: async (request, input, by) => (await import("../lib/review-client")).answerReviewRequest(request, input, by),
  saveDraftDecision: async (request, draftId, decision) => (await import("../lib/review-client")).saveDraftDecision(request, draftId, decision),
  markReviewRead: async (userKey, requestId) => (await import("../lib/review-client")).markReviewRead(userKey, requestId),
  transitionProposalPath: async (proposalId, path) => (await import("../lib/proposals-client")).transitionProposalPath(proposalId, path),
  loadHeldEmails: async () => {
    const { loadMonitoringPage } = await import("../lib/monitoring-client");
    const rows: MonitoringEmailSummary[] = [];
    let cursor: string | null = null;
    do {
      const page = await loadMonitoringPage("emailSubmissions", cursor, "publication", true);
      if (!("rows" in page)) return rows;
      rows.push(...(page.rows as MonitoringEmailSummary[]));
      cursor = page.cursor;
    } while (cursor);
    return rows;
  },
  loadEmail: async (receiptId) => (await import("../lib/monitoring-client")).loadMonitoringEmailSubmission(receiptId),
  decideEmail: async (receiptId, decision, reason) => (await import("../lib/monitoring-client")).decideMonitoringEmailSubmission(receiptId, decision, reason),
};

/** The demo and the real-data preview answer in memory with the same rules as the live data API; nothing leaves the page. */
const demoApi: NotificationApi = {
  loadReviews: async () => ({ state: "unavailable" }),
  loadDrafts: async () => ({ drafts: {}, missing: [], failed: [] }),
  loadStoryTitles: async () => ({ titles: {}, deleted: [] }),
  answerReviewRequest: async (request, input, by) => {
    const update = answerUpdate(request, input, by, new Date());
    return { ...request, state: "answered", answer: JSON.parse(String(update.answer)), links: update.links ? JSON.parse(String(update.links)) : request.links, history: JSON.parse(String(update.history)), updatedAt: String(update.updatedAt) };
  },
  saveDraftDecision: async (request, draftId, decision) => {
    const update = draftDecisionUpdate(request, draftId, decision);
    return { ...request, links: JSON.parse(String(update.links)), history: JSON.parse(String(update.history)), updatedAt: String(update.updatedAt) };
  },
  markReviewRead: async () => undefined,
  transitionProposalPath: async () => ({ status: "ok" }),
  loadHeldEmails: async () => FIXTURE_HELD_EMAILS,
  loadEmail: async (receiptId) => FIXTURE_EMAIL_DETAILS[receiptId] ?? { state: "unavailable" },
  decideEmail: async (_receiptId, decision) => ({ ok: true, already: false, quarantine: { state: decision === "accept" ? "released" : "discarded", decision: null, failure: null } }),
};

type ContainerProps = {
  references: ReferenceRecord[];
  decisions: ReadonlyMap<string, RelevanceDecisionView>;
  humanCuratedReferenceLineageIds?: ReadonlySet<string>;
  previews?: ReadonlyMap<string, ReferencePreview>;
  referencesLoading?: boolean;
  predictionLoading?: boolean;
  referenceDisabledReason?: string | null;
  onRateReference?: (reference: ReferenceRecord, choice: ReviewChoice, reasonCode: ReferenceRejectionReasonCode | null, note?: string) => Promise<void> | void;
  /** The Reference attachments (previews, captured text), for the cards' pictures and the capture checks. */
  referenceAttachments?: ReferenceAttachmentRecord[];
  /** Saves a pasted or corrected capture. Without it the capture panel has no edit action. */
  onCorrectCapture?: CorrectCaptureAction;
  actorLabel: string;
  demo: boolean;
  /** A real-data preview (see scripts/export-notification-center-fixture.py); the invented sample otherwise. */
  fixture?: NotificationFixture | null;
  api?: NotificationApi;
};

const REFRESH_MILLISECONDS = 60_000;

/** Preview only: ?ncState=loading holds the skeleton, caught-up shows the empty state, sample swaps in the invented hard gate, flags, batches and held email, mixed adds the invented hard gate, flag and held email to the real data. */
function previewState(): "loading" | "caught-up" | "sample" | "mixed" | null {
  if (typeof window === "undefined" || !isLocalPreviewEnabled()) return null;
  const requested = new URLSearchParams(window.location.search).get("ncState");
  return requested === "loading" || requested === "caught-up" || requested === "sample" || requested === "mixed" ? requested : null;
}

const EMAIL_REFUSALS: Record<string, string> = {
  forbidden: "Your session cannot decide held email.",
  bad_request: "That email could not be decided from here.",
  already_decided: "Someone already decided this email. Refresh to see what they chose.",
  not_quarantined: "This email is no longer held.",
  expired: "This email expired and can no longer be accepted.",
};

export function NotificationCenter({
  references, decisions, humanCuratedReferenceLineageIds = NO_VISIT, previews = NO_PREVIEWS, referencesLoading = false, predictionLoading = false, referenceDisabledReason = null,
  onRateReference, referenceAttachments = NO_ATTACHMENTS, onCorrectCapture, actorLabel, demo, fixture = null, api: liveOverride = liveApi,
}: ContainerProps) {
  const api = demo ? demoApi : liveOverride;
  const [loadState, setLoadState] = useState<NotificationLoadState>("loading");
  const [stale, setStale] = useState(false);
  const [requests, setRequests] = useState<ReviewRequest[]>([]);
  const [userKey, setUserKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [storyTitles, setStoryTitles] = useState<Record<string, string>>({});
  const [storyExcerpts, setStoryExcerpts] = useState<Record<string, string>>({});
  const [deletedStories, setDeletedStories] = useState<ReadonlySet<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, DraftView>>({});
  const [missingDrafts, setMissingDrafts] = useState<ReadonlySet<string>>(new Set());
  const [draftsState, setDraftsState] = useState<DraftsLoadState>("loading");
  const [emails, setEmails] = useState<MonitoringEmailSummary[]>([]);
  const [emailsState, setEmailsState] = useState<"loading" | "ready">("loading");
  const [emailsDecided, setEmailsDecided] = useState<ReadonlyMap<string, "accept" | "reject">>(new Map());
  const [stay, setStay] = useState<ReadonlySet<string>>(new Set());
  const [visitRated, setVisitRated] = useState<ReadonlySet<string>>(new Set());
  const [now] = useState(() => Date.now());
  const resolving = useRef(new Set<string>());
  const demoStarted = useRef(false);
  const preview = useMemo(() => previewState(), []);
  const sample = useMemo(() => {
    if (preview === "sample" || !fixture) return { requests: FIXTURE_REVIEW_REQUESTS, drafts: FIXTURE_DRAFTS };
    if (preview === "mixed") {
      const invented = FIXTURE_REVIEW_REQUESTS.filter((request) => request.id === "rr-hard-1" || request.id === "rr-flag-1");
      return { requests: [...invented, ...fixture.requests], drafts: fixture.drafts };
    }
    return { requests: preview === "caught-up" ? [] : fixture.requests, drafts: fixture.drafts };
  }, [fixture, preview]);

  const keep = useCallback((key: string) => setStay((current) => (current.has(key) ? current : new Set(current).add(key))), []);

  const loadDraftsFor = useCallback(async (list: ReviewRequest[]) => {
    const ids = list.filter((request) => request.state === "open" && isDraftReview(request)).flatMap(draftIdsOf);
    if (!ids.length) {
      setDraftsState("ready");
      return;
    }
    if (demo) {
      const known = sample.drafts.filter((row) => ids.includes(row.id));
      setDrafts((current) => ({ ...current, ...Object.fromEntries(known.map((row) => [row.id, draftView(row, true)])) }));
      setMissingDrafts(new Set(ids.filter((id) => !known.some((row) => row.id === id))));
      setDraftsState("ready");
      return;
    }
    try {
      const loaded = await api.loadDrafts(ids);
      setDrafts((current) => ({ ...current, ...loaded.drafts }));
      setMissingDrafts(new Set(loaded.missing));
      setDraftsState(loaded.failed.length ? "failed" : "ready");
    } catch {
      setDraftsState("failed");
    }
  }, [api, demo, sample]);

  // Email held for review is read on its own: a site without monitoring, or an editor who may not read it, simply has none.
  const loadEmailsNow = useCallback(async () => {
    if (preview === "caught-up") { setEmails([]); setEmailsState("ready"); return; }
    // The real-data preview has no held email of its own; only the sample and mixed previews show the invented one.
    if (demo && fixture && preview !== "sample" && preview !== "mixed") { setEmails(fixture.emails ?? []); setEmailsState("ready"); return; }
    try {
      setEmails((await api.loadHeldEmails?.()) ?? []);
    } catch {
      // Held email is one source among several; the others still show.
    }
    setEmailsState("ready");
  }, [api, demo, fixture, preview]);

  // A return visit paints the last view at once, marked as such, while the real reads run.
  useEffect(() => {
    if (demo) return;
    const snapshot = loadNotificationSnapshot(SITE_BRAND.id);
    if (!snapshot) return;
    setRequests(snapshot.requests);
    setDrafts(snapshot.drafts);
    setMissingDrafts(new Set(snapshot.missing));
    setDraftsState("ready");
    setStale(true);
    setLoadState((current) => (current === "loading" ? "ready" : current));
  }, [demo]);

  const refresh = useCallback(async () => {
    if (demo) {
      // The sample is read once: answering in the preview must not be undone by the next refresh.
      if (demoStarted.current) return;
      demoStarted.current = true;
      setRequests(sample.requests);
      setLoadState("ready");
      void loadDraftsFor(sample.requests);
      void loadEmailsNow();
      return;
    }
    try {
      const loaded = await api.loadReviews();
      if (loaded.state !== "ready") {
        setStale(false);
        setLoadState(loaded.state);
        return;
      }
      setRequests(loaded.requests);
      setUserKey(loaded.userKey);
      setStale(false);
      setLoadState("ready");
      void loadDraftsFor(loaded.requests);
      void loadEmailsNow();
      const stories = await api.loadStoryTitles(loaded.requests.filter((request) => request.subject.type === "story").map((request) => request.subject.id)).catch(() => ({ titles: {}, deleted: [] as string[], excerpts: {} }));
      setStoryTitles(stories.titles);
      setStoryExcerpts(stories.excerpts ?? {});
      setDeletedStories(new Set(stories.deleted));
    } catch {
      setStale(false);
      setLoadState("unavailable");
    }
  }, [api, demo, loadDraftsFor, loadEmailsNow, sample]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MILLISECONDS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  // Keep a display copy for the next visit once the live read and its drafts have arrived.
  useEffect(() => {
    if (demo || stale || loadState !== "ready" || draftsState !== "ready") return;
    const timer = window.setTimeout(() => saveNotificationSnapshot(SITE_BRAND.id, { requests, drafts, missing: missingDrafts }), 800);
    return () => window.clearTimeout(timer);
  }, [demo, draftsState, drafts, loadState, missingDrafts, requests, stale]);

  const markRead = useCallback(async (requestId: string) => {
    if (demo || !userKey) return;
    await api.markReviewRead(userKey, requestId).catch(() => undefined);
  }, [api, demo, userKey]);

  /** Answers a whole request. Throws a sentence for the card when it cannot be saved. */
  const answer = useCallback(async (request: ReviewRequest, input: AnswerInput) => {
    setError(null);
    const saved = await api.answerReviewRequest(request, input, actorLabel);
    keep(request.id);
    setRequests((current) => current.map((entry) => (entry.id === saved.id ? saved : entry)));
    await markRead(request.id);
  }, [actorLabel, api, keep, markRead]);

  /** Accept or Reject one draft: the Proposal moves to approved or declined, the decision is recorded on the request, and the request closes once every draft is decided. */
  const decideDraft = useCallback(async (request: ReviewRequest, draftId: string, choice: DraftChoice, extras: { why: string; notThisKind: boolean }) => {
    setError(null);
    resolving.current.add(request.id);
    try {
      const view = drafts[draftId];
      if (!view) throw new Error("This draft has not loaded yet.");
      const path = choice === "accept" ? acceptPath(view.state) : rejectPath(view.state);
      if (!path) throw new Error(`This draft is ${stateLabel(view.state, false).toLowerCase()} and cannot be ${choice === "accept" ? "accepted" : "rejected"} from here. Open it in Proposals.`);
      const receipt = await api.transitionProposalPath(draftId, path);
      if (receipt.status !== "ok") throw new Error(proposalReceiptMessage(receipt));
      const decided: DraftView = { ...view, state: choice === "accept" ? "approved" : "declined", decided: choice };
      const nextDrafts = { ...drafts, [draftId]: decided };
      setDrafts(nextDrafts);
      keep(`${request.id}#${draftId}`);
      const decision: DraftDecision = { choice, title: view.headline, why: extras.why || null, notThisKind: choice === "reject" && extras.notThisKind, by: actorLabel, at: new Date().toISOString() };
      const withDecisionRequest = { ...request, links: withDecision(request, draftId, decision) };
      const closing = batchAnswer(withDecisionRequest, nextDrafts, { by: actorLabel, at: decision.at });
      try {
        const saved = closing ? await api.answerReviewRequest(request, closing, actorLabel) : await api.saveDraftDecision(request, draftId, decision);
        setRequests((current) => current.map((entry) => (entry.id === saved.id ? saved : entry)));
        if (closing) await markRead(request.id);
      } catch (failure) {
        throw new Error(`The draft was ${choice === "accept" ? "accepted" : "rejected"} in Proposals, but this request could not record it. ${failure instanceof Error ? failure.message : ""}`.trim());
      }
    } catch (failure) {
      if (!demo) void loadDraftsFor([request]);
      throw failure;
    } finally {
      resolving.current.delete(request.id);
    }
  }, [actorLabel, api, demo, drafts, keep, loadDraftsFor, markRead]);

  // Drafts decided in Proposals (not here) still close their request.
  useEffect(() => {
    if (demo || draftsState !== "ready" || stale) return;
    for (const request of requests) {
      if (request.state !== "open" || !isDraftReview(request) || resolving.current.has(request.id)) continue;
      if (undecidedDraftIds(request, drafts).length) continue;
      const closing = batchAnswer(request, drafts, { by: "an editor in Proposals", at: new Date().toISOString() });
      if (!closing) continue;
      resolving.current.add(request.id);
      void (async () => {
        try {
          const saved = await api.answerReviewRequest(request, closing, "an editor in Proposals");
          setRequests((current) => current.map((entry) => (entry.id === saved.id ? saved : entry)));
        } catch {
          // The next refresh shows what became of it.
        } finally {
          resolving.current.delete(request.id);
        }
      })();
    }
  }, [api, demo, drafts, draftsState, requests, stale]);

  /** One decision, whatever the type: it goes to the action that already owns that kind of thing. */
  const decide = useCallback(async (item: NeedsMeEntry, decision: NeedsMeDecision) => {
    const { payload } = item;
    if (payload.kind === "reference") {
      setVisitRated((current) => (current.has(payload.lineageId) ? current : new Set(current).add(payload.lineageId)));
      await onRateReference?.(payload.reference, decision.choice, decision.choice === "reject" ? decision.reasonCode : null, decision.why || undefined);
    } else if (payload.kind === "draft") {
      await decideDraft(payload.item.request, payload.item.draftId, decision.choice, { why: decision.why, notThisKind: decision.notThisKind });
    } else if (payload.kind === "request") {
      const { request } = payload;
      if (request.mode === "flag") await answer(request, { decision: "acknowledge", feedback: decision.why || null });
      else if (decision.choice === "accept") await answer(request, { decision: "approve", feedback: decision.why || null });
      else await answer(request, { decision: "reject", feedback: decision.why || null, steer: decision.notThisKind ? "not_this_kind" : null });
    } else if (payload.kind === "email") {
      const result = await api.decideEmail?.(payload.summary.receiptId, decision.choice, decision.why);
      if (!result) throw new Error("Held email cannot be decided from here.");
      if (!("ok" in result)) throw new Error("error" in result ? EMAIL_REFUSALS[result.error] ?? "The decision could not be saved." : "The decision could not be saved right now. Try again in a minute.");
      setEmailsDecided((current) => new Map(current).set(payload.summary.receiptId, decision.choice));
    }
  }, [answer, api, decideDraft, onRateReference]);

  const shownReferences = preview === "caught-up" ? references.filter((reference) => normalizeReferenceCurationStatus(reference.curationStatus) !== "pending") : references;
  const bySource = useMemo(() => previewsBySourceAddress(shownReferences, previews), [shownReferences, previews]);
  const lineageIds = useMemo(() => shownReferences.map(referenceLineageId), [shownReferences]);
  const { statuses: captures, teaserLine } = useMemo(() => captureStatusesByLineage(referenceAttachments, lineageIds), [lineageIds, referenceAttachments]);

  const entries = useMemo(
    () => buildNeedsMeItems({
      references: shownReferences, decisions, previews, captures, visitRated, requests, drafts, missingDrafts, draftsState, stay, bySource,
      storyTitles, storyExcerpts, deletedStories, emails, emailsDecided,
    }),
    [shownReferences, decisions, previews, captures, visitRated, requests, drafts, missingDrafts, draftsState, stay, bySource, storyTitles, storyExcerpts, deletedStories, emails, emailsDecided],
  );
  const freshness = useMemo(() => learnFreshness(shownReferences, visitRated), [shownReferences, visitRated]);
  const threshold = useMemo(() => learnConfidenceThreshold(shownReferences, decisions, visitRated), [shownReferences, decisions, visitRated]);
  const recent = useMemo(() => recentDecisions(requests, references, demo), [requests, references, demo]);
  const shaping = useMemo(
    () => shapingThisWeek({ decidedAt: recentDecisions(requests, references, demo, Number.MAX_SAFE_INTEGER).map((entry) => entry.at), references, decisions, now }),
    [requests, references, demo, decisions, now],
  );
  const shownIds = useMemo(() => new Set(entries.map((item) => item.id)), [entries]);
  const legacyAuto = useMemo(
    () => cyclotronAutoDecided(shownReferences, decisions, humanCuratedReferenceLineageIds, demo).filter((entry) => !shownIds.has(entry.lineageId)),
    [shownReferences, decisions, humanCuratedReferenceLineageIds, demo, shownIds],
  );
  const openDraftRequests = useMemo(() => sectionReviews(requests).draftBatches, [requests]);
  const missingCount = openDraftRequests.reduce((total, request) => total + draftIdsOf(request).filter((id) => missingDrafts.has(id)).length, 0);
  const settled = !stale && loadState === "ready" && draftsState !== "loading" && emailsState === "ready" && !referencesLoading && !predictionLoading;

  return (
    <NeedsMeView
      captureTeaserLine={teaserLine} demo={demo} draftsFailed={draftsState === "failed"} entries={entries} error={error} freshness={freshness} legacyAuto={legacyAuto}
      loadEmail={api.loadEmail} loadState={preview === "loading" ? "loading" : loadState} missingDraftCount={missingCount} now={now} onCorrectCapture={onCorrectCapture} onDecide={decide}
      onRetryDrafts={() => void loadDraftsFor(requests)} predictionLoading={predictionLoading} recent={recent} referenceAttachments={referenceAttachments}
      referenceDisabledReason={referenceDisabledReason} referencesLoading={referencesLoading} settled={settled} shaping={shaping} stale={stale} threshold={threshold}
    />
  );
}
