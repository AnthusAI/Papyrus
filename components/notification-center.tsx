"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import type { EmailDecisionResult, MonitoringEmailDetails, MonitoringEmailSummary } from "../lib/monitoring-overview";
import type { ReviewLoad } from "../lib/review-client";
import { recentDecisions } from "../lib/notification-feed";
import { answerReasonUpdate, answerUpdate, applyReviewUpdate, cyclotronAutoDecided, ideaIdsOf, isIdeaBatch, type AnswerInput, type ReviewRequest } from "../lib/review-requests";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { learnConfidenceThreshold, shapingThisWeek } from "../lib/needs-me-ranking";
import { buildNeedsMeItems } from "../lib/needs-me-items";
import { captureStatusesByLineage } from "../lib/reference-capture";
import { normalizeReferenceCurationStatus, type ReferenceRejectionReasonCode } from "../lib/reference-policy";
import type { ReferencePreview } from "../lib/reference-preview";
import { referenceLineageId } from "../lib/newsroom-references";
import { loadNotificationSnapshot, saveNotificationSnapshot } from "../lib/reference-feed-cache";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { SITE_BRAND } from "../lib/site-brand";
import { FIXTURE_IDEAS, FIXTURE_EMAIL_DETAILS, FIXTURE_HELD_EMAILS, FIXTURE_REVIEW_REQUESTS } from "../lib/review-fixture";
import { NeedsMeView, type NeedsMeDecision } from "./needs-me-feed";
import type { NeedsMeEntry } from "../lib/needs-me-items";
import type { CorrectCaptureAction } from "./reference-capture-client";
import type { ReviewChoice } from "./reference-review-card";

export type NotificationLoadState = "loading" | "ready" | "forbidden" | "unavailable";

/** What a real-data preview shows instead of the invented sample (scripts/export-notification-center-fixture.py). */
export type NotificationFixture = { requests: ReviewRequest[]; emails?: MonitoringEmailSummary[] };

const NO_VISIT: ReadonlySet<string> = new Set();
const NO_PREVIEWS: ReadonlyMap<string, ReferencePreview> = new Map();
const NO_ATTACHMENTS: ReferenceAttachmentRecord[] = [];

/** Everything the container reads and writes. The live one talks to the site's data API; tests pass a fake. */
export type NotificationApi = {
  loadReviews: () => Promise<ReviewLoad>;
  /** Titles and current stages of the stories and ideas the requests name, by lineage id. */
  loadStoryTitles: (ids: string[]) => Promise<{ titles: Record<string, string>; deleted: string[]; excerpts?: Record<string, string>; stages?: Record<string, string> }>;
  answerReviewRequest: (request: ReviewRequest, input: AnswerInput, by: string) => Promise<ReviewRequest>;
  /** Changes only the note of a request that is already answered (`answerReasonUpdate`). Returns the saved request. */
  saveReviewReason: (request: ReviewRequest, update: Record<string, unknown>) => Promise<ReviewRequest>;
  markReviewRead: (userKey: string, requestId: string) => Promise<void>;
  /** Email submissions held for review (Monitoring's own read). Optional: a site without monitoring has none. */
  loadHeldEmails?: () => Promise<MonitoringEmailSummary[]>;
  loadEmail?: (receiptId: string) => Promise<MonitoringEmailDetails>;
  decideEmail?: (receiptId: string, decision: "accept" | "reject", reason: string) => Promise<EmailDecisionResult>;
};

const liveApi: NotificationApi = {
  loadReviews: async () => (await import("../lib/review-client")).loadReviews(),
  loadStoryTitles: async (ids) => (await import("../lib/review-client")).loadStoryTitles(ids),
  answerReviewRequest: async (request, input, by) => (await import("../lib/review-client")).answerReviewRequest(request, input, by),
  saveReviewReason: async (request, update) => (await import("../lib/review-client")).saveReviewReason(request, update),
  markReviewRead: async (userKey, requestId) => (await import("../lib/review-client")).markReviewRead(userKey, requestId),
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
  loadStoryTitles: async (ids) => ({
    titles: Object.fromEntries(FIXTURE_IDEAS.filter((idea) => ids.includes(idea.id)).map((idea) => [idea.id, idea.title])), deleted: [],
    stages: Object.fromEntries(FIXTURE_IDEAS.filter((idea) => ids.includes(idea.id)).map((idea) => [idea.id, idea.stage])),
  }),
  answerReviewRequest: async (request, input, by) => {
    const update = answerUpdate(request, input, by, new Date());
    return { ...request, state: "answered", answer: JSON.parse(String(update.answer)), history: JSON.parse(String(update.history)), updatedAt: String(update.updatedAt) };
  },
  saveReviewReason: async (request, update) => applyReviewUpdate(request, update),
  markReviewRead: async () => undefined,
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
  /** Other page sections, shown at the end of the feed's own scroll. */
  below?: ReactNode;
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
  already_applied: "This email was already queued, so its reason can no longer be changed here.",
  already_decided: "Someone already decided this email. Refresh to see what they chose.",
  not_quarantined: "This email is no longer held.",
  expired: "This email expired and can no longer be accepted.",
};

export function NotificationCenter({
  references, decisions, humanCuratedReferenceLineageIds = NO_VISIT, previews = NO_PREVIEWS, referencesLoading = false, predictionLoading = false, referenceDisabledReason = null,
  onRateReference, referenceAttachments = NO_ATTACHMENTS, onCorrectCapture, actorLabel, demo, fixture = null, api: liveOverride = liveApi, below,
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
  const [ideaStages, setIdeaStages] = useState<Record<string, string>>({});
  const [emails, setEmails] = useState<MonitoringEmailSummary[]>([]);
  const [emailsState, setEmailsState] = useState<"loading" | "ready">("loading");
  const [emailsDecided, setEmailsDecided] = useState<ReadonlyMap<string, "accept" | "reject">>(new Map());
  const [stay, setStay] = useState<ReadonlySet<string>>(new Set());
  const [visitRated, setVisitRated] = useState<ReadonlySet<string>>(new Set());
  const [now] = useState(() => Date.now());
  const demoStarted = useRef(false);
  const preview = useMemo(() => previewState(), []);
  const sample = useMemo(() => {
    if (preview === "sample" || !fixture) return { requests: FIXTURE_REVIEW_REQUESTS };
    if (preview === "mixed") {
      const invented = FIXTURE_REVIEW_REQUESTS.filter((request) => request.id === "rr-hard-1" || request.id === "rr-flag-1");
      return { requests: [...invented, ...fixture.requests] };
    }
    return { requests: preview === "caught-up" ? [] : fixture.requests };
  }, [fixture, preview]);

  const keep = useCallback((key: string) => setStay((current) => (current.has(key) ? current : new Set(current).add(key))), []);

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
    setStale(true);
    setLoadState((current) => (current === "loading" ? "ready" : current));
  }, [demo]);

  /** The titles and stages of the stories that open requests are about, and of the ideas the open batches name. */
  const loadStoriesFor = useCallback(async (list: ReviewRequest[]) => {
    const open = list.filter((request) => request.state === "open");
    const ids = [...open.filter((request) => request.subject.type === "story").map((request) => request.subject.id), ...open.filter(isIdeaBatch).flatMap(ideaIdsOf)];
    const stories = await api.loadStoryTitles(ids).catch(() => ({ titles: {}, deleted: [] as string[], excerpts: {}, stages: {} }));
    setStoryTitles(stories.titles);
    setStoryExcerpts(stories.excerpts ?? {});
    setIdeaStages(stories.stages ?? {});
    setDeletedStories(new Set(stories.deleted));
  }, [api]);

  const refresh = useCallback(async () => {
    if (demo) {
      // The sample is read once: answering in the preview must not be undone by the next refresh.
      if (demoStarted.current) return;
      demoStarted.current = true;
      setRequests(sample.requests);
      setLoadState("ready");
      void loadEmailsNow();
      void loadStoriesFor(sample.requests);
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
      void loadEmailsNow();
      await loadStoriesFor(loaded.requests);
    } catch {
      setStale(false);
      setLoadState("unavailable");
    }
  }, [api, demo, loadEmailsNow, loadStoriesFor, sample]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MILLISECONDS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  // Keep a display copy for the next visit once the live read has arrived.
  useEffect(() => {
    if (demo || stale || loadState !== "ready") return;
    const timer = window.setTimeout(() => saveNotificationSnapshot(SITE_BRAND.id, { requests }), 800);
    return () => window.clearTimeout(timer);
  }, [demo, loadState, requests, stale]);

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

  /** Accept or Reject a held email, or (the same choice again) correct the reason it was given. The reason shown is what the server recorded. */
  const sendEmailDecision = useCallback(async (summary: MonitoringEmailSummary, choice: "accept" | "reject", why: string, editing = false) => {
    const result = await api.decideEmail?.(summary.receiptId, choice, why);
    if (!result) throw new Error("Held email cannot be decided from here.");
    if (!("ok" in result)) throw new Error("error" in result ? EMAIL_REFUSALS[result.error] ?? "The decision could not be saved." : "The decision could not be saved right now. Try again in a minute.");
    const plain = (text: string) => text.replace(/\s+/g, " ").trim().slice(0, 500);
    const recorded = result.quarantine?.decision;
    // The server keeps the first reason once it has queued the email; say so in words rather than showing a reason that was not kept.
    if (editing && recorded && plain(recorded.reason) !== plain(why)) throw new Error(EMAIL_REFUSALS.already_applied);
    const kept = recorded?.reason ?? plain(why);
    setEmailsDecided((current) => new Map(current).set(summary.receiptId, choice));
    setEmails((current) => current.map((entry) => (entry.receiptId === summary.receiptId
      ? { ...entry, quarantine: { state: entry.quarantine?.state ?? "quarantined", failure: entry.quarantine?.failure ?? null, decision: { action: choice, by: recorded?.by || actorLabel, at: recorded?.at ?? new Date().toISOString(), reason: kept, viaGroup: recorded?.viaGroup } } }
      : entry)));
  }, [actorLabel, api]);

  /**
   * Changes only the Why of an item that is already decided, onto the decision that exists:
   *   review request    the request's answer note (a hard gate, a stage review, an acknowledged flag)
   *   held email        the same decision again with the new reason, so the Monitoring view updates the recorded reason
   */
  const latest = useRef({ requests, emails, emailsDecided });
  latest.current = { requests, emails, emailsDecided };
  const editReason = useCallback(async (item: NeedsMeEntry, why: string) => {
    const { payload } = item;
    const now = new Date();
    const store = (saved: ReviewRequest) => {
      latest.current.requests = latest.current.requests.map((entry) => (entry.id === saved.id ? saved : entry));
      setRequests((current) => current.map((entry) => (entry.id === saved.id ? saved : entry)));
    };
    if (payload.kind === "request") {
      const request = latest.current.requests.find((entry) => entry.id === payload.request.id) ?? payload.request;
      store(await api.saveReviewReason(request, answerReasonUpdate(request, why, actorLabel, now)));
    } else if (payload.kind === "email") {
      const choice = latest.current.emailsDecided.get(payload.summary.receiptId) ?? payload.summary.quarantine?.decision?.action;
      if (!choice) throw new Error("This email has not been decided yet.");
      await sendEmailDecision(payload.summary, choice, why, true);
    }
  }, [actorLabel, api, sendEmailDecision]);

  /** One decision, whatever the type: it goes to the action that already owns that kind of thing. */
  const decide = useCallback(async (item: NeedsMeEntry, decision: NeedsMeDecision) => {
    const { payload } = item;
    if (payload.kind === "reference") {
      setVisitRated((current) => (current.has(payload.lineageId) ? current : new Set(current).add(payload.lineageId)));
      await onRateReference?.(payload.reference, decision.choice, decision.choice === "reject" ? decision.reasonCode : null, decision.why || undefined);
    } else if (payload.kind === "request") {
      const { request } = payload;
      if (request.mode === "flag") await answer(request, { decision: "acknowledge", feedback: decision.why || null });
      else if (decision.choice === "accept") await answer(request, { decision: "approve", feedback: decision.why || null });
      else await answer(request, { decision: "reject", feedback: decision.why || null, steer: decision.notThisKind ? "not_this_kind" : null });
    } else if (payload.kind === "email") {
      await sendEmailDecision(payload.summary, decision.choice, decision.why);
    }
  }, [answer, onRateReference, sendEmailDecision]);

  const shownReferences = preview === "caught-up" ? references.filter((reference) => normalizeReferenceCurationStatus(reference.curationStatus) !== "pending") : references;
  const lineageIds = useMemo(() => shownReferences.map(referenceLineageId), [shownReferences]);
  const { statuses: captures, teaserLine } = useMemo(() => captureStatusesByLineage(referenceAttachments, lineageIds), [lineageIds, referenceAttachments]);

  const entries = useMemo(
    () => buildNeedsMeItems({
      references: shownReferences, decisions, previews, captures, visitRated, requests, stay, demo, ideaStages,
      storyTitles, storyExcerpts, deletedStories, emails, emailsDecided,
    }),
    [shownReferences, decisions, previews, captures, visitRated, requests, stay, demo, ideaStages, storyTitles, storyExcerpts, deletedStories, emails, emailsDecided],
  );
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
  const settled = !stale && loadState === "ready" && emailsState === "ready" && !referencesLoading && !predictionLoading;

  return (
    <NeedsMeView
      below={below} captureTeaserLine={teaserLine} demo={demo} entries={entries} error={error} legacyAuto={legacyAuto}
      loadEmail={api.loadEmail} loadState={preview === "loading" ? "loading" : loadState} now={now} onCorrectCapture={onCorrectCapture} onDecide={decide} onEditReason={editReason}
      predictionLoading={predictionLoading} recent={recent} referenceAttachments={referenceAttachments}
      referenceDisabledReason={referenceDisabledReason} referencesLoading={referencesLoading} settled={settled} shaping={shaping} stale={stale} threshold={threshold}
    />
  );
}
