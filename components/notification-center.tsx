"use client";

import { CheckIcon, CircleCheckIcon, CircleDotIcon, CircleXIcon, ClockIcon, ExternalLinkIcon, FlagIcon, HourglassIcon, LockIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { proposalReceiptMessage, stateLabel, type ProposalReceipt } from "../lib/proposals-admin";
import type { DraftLoad, ReviewLoad } from "../lib/review-client";
import { acceptPath, batchAnswer, cannotMoveReason, draftDecisionOf, draftsToDecide, draftView, rejectPath, undecidedDraftIds, withDecision, type DraftChoice, type DraftView } from "../lib/review-drafts";
import {
  cyclotronAutoDecided, cyclotronHeldForReview, draftIdsOf, formatWhen, isDraftReview, isUnread, modeLabel, nextText, proposalHref, sectionReviews,
  steeringText, subjectHref, subjectLabel, summarize, summaryText,
  type AnswerInput, type CyclotronEntry, type DraftDecision, type ReviewRequest,
} from "../lib/review-requests";
import type { ReferenceRecord } from "../lib/category-repository";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { FIXTURE_DRAFTS, FIXTURE_REVIEW_REQUESTS } from "../lib/review-fixture";
import { ChoiceButtons } from "./reference-review-card";

export type NotificationLoadState = "loading" | "ready" | "forbidden" | "unavailable";
export type DraftsLoadState = "loading" | "ready" | "failed";
export type DraftExtras = { why: string; notThisKind: boolean };

type ViewProps = {
  loadState: NotificationLoadState;
  requests: ReviewRequest[];
  readIds: ReadonlySet<string>;
  held: CyclotronEntry[];
  autoDecided: CyclotronEntry[];
  storyTitles?: Readonly<Record<string, string>>;
  deletedStories?: ReadonlySet<string>;
  demo?: boolean;
  busyId?: string | null;
  error?: string | null;
  /** The AI drafts that draft reviews are about, by proposal id, and which ids have no proposal on this site. */
  drafts?: Readonly<Record<string, DraftView>>;
  missingDrafts?: ReadonlySet<string>;
  draftsState?: DraftsLoadState;
  /** Keyed `<request id>#<draft id>`. */
  draftErrors?: Readonly<Record<string, string>>;
  draftBusyId?: string | null;
  onAnswer?: (request: ReviewRequest, input: AnswerInput) => void;
  onDecideDraft?: (request: ReviewRequest, draftId: string, choice: DraftChoice, extras: DraftExtras) => void;
  onRetryDrafts?: () => void;
  onMarkRead?: (requestId: string) => void;
  onMarkAllRead?: () => void;
};

const CONTROL_ICON = { hard_gate: LockIcon, soft_review: ClockIcon, flag: FlagIcon } as const;
const NOT_THIS_KIND = { request: "Not this kind of thing", draft: "Not this kind of story" } as const;

function WhyBox({ busy, onChange, placeholder, value }: { busy: boolean; onChange: (value: string) => void; placeholder: string; value: string }) {
  return (
    <label className="block text-sm font-medium">
      Why? (optional)
      <textarea
        aria-label="Why? (optional)"
        className="mt-1 block min-h-20 w-full rounded-md border bg-background p-3 text-base font-normal"
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        readOnly={busy}
        value={value}
      />
    </label>
  );
}

function NotThisKind({ busy, label, onToggle, pressed }: { busy: boolean; label: string; onToggle: () => void; pressed: boolean }) {
  return (
    <div className="space-y-1" data-review-reasons>
      <p className="text-sm font-medium">If you reject it</p>
      <Button aria-disabled={busy || undefined} aria-pressed={pressed} className="min-h-10" data-review-reason="not_this_kind" onClick={() => { if (!busy) onToggle(); }} type="button" variant={pressed ? "default" : "outline"}>
        {pressed ? <CheckIcon aria-hidden="true" className="size-4" /> : null}
        {label}
      </Button>
    </div>
  );
}

/** Accept or Reject on the request itself: a hard gate, a soft review without drafts, or a draft review whose drafts could not be loaded. */
function RequestControls({ request, busy, unread, onAnswer, onMarkRead }: { request: ReviewRequest; busy: boolean; unread: boolean; onAnswer?: ViewProps["onAnswer"]; onMarkRead?: ViewProps["onMarkRead"] }) {
  const [note, setNote] = useState("");
  const [notThisKind, setNotThisKind] = useState(false);
  const flag = request.mode === "flag";
  const act = (input: AnswerInput) => { if (!busy) onAnswer?.(request, { ...input, feedback: note.trim() || null }); };
  return (
    <div className="space-y-3" data-review-controls>
      {flag ? (
        <Button aria-disabled={busy || undefined} className="min-h-12 w-full text-base" onClick={() => act({ decision: "acknowledge" })} type="button" variant="outline">Acknowledge</Button>
      ) : (
        <ChoiceButtons chosen={null} disabled={busy} onChoose={(choice) => act(choice === "accept" ? { decision: "approve" } : { decision: "reject", steer: notThisKind ? "not_this_kind" : null })} />
      )}
      <div aria-live="polite" className="min-h-5 text-sm" role="status">{busy ? "Saving…" : ""}</div>
      <WhyBox busy={busy} onChange={setNote} placeholder={flag ? "Optional. Tell the step what to do differently." : "Optional. Write it before you tap Accept or Reject; it is saved with your answer."} value={note} />
      {flag ? null : <NotThisKind busy={busy} label={NOT_THIS_KIND.request} onToggle={() => setNotThisKind((current) => !current)} pressed={notThisKind} />}
      {unread ? <Button aria-disabled={busy || undefined} onClick={() => { if (!busy) onMarkRead?.(request.id); }} size="sm" variant="ghost">Mark read</Button> : null}
    </div>
  );
}

function DecidedLine({ choice, notThisKind, why }: { choice: "accept" | "reject"; notThisKind?: boolean; why?: string | null }) {
  const Icon = choice === "accept" ? CircleCheckIcon : CircleXIcon;
  return (
    <p className="flex items-start gap-1.5 text-sm font-medium" data-draft-decided={choice}>
      <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span className="break-words">
        {choice === "accept" ? "Accepted" : "Rejected"}{choice === "reject" && notThisKind ? " as not this kind of story" : ""}
        {why ? <span className="font-normal text-muted-foreground">: {why}</span> : null}
      </span>
    </p>
  );
}

/** One AI draft, shown so it can be judged in place: headline, dek, section, evidence, sources and the way to the full draft. */
function DraftCard({ id, view, request, busy, error, onDecide }: {
  id: string; view: DraftView | undefined; request: ReviewRequest; busy: boolean; error: string | null;
  onDecide?: (draftId: string, choice: DraftChoice, extras: { why: string; notThisKind: boolean }) => void;
}) {
  const [why, setWhy] = useState("");
  const [notThisKind, setNotThisKind] = useState(false);
  const link = request.links.find((entry) => entry.id === id);
  const decision = draftDecisionOf(link, view, { by: "", at: "" });
  const hold = view ? cannotMoveReason(view) : null;
  if (!view) {
    return (
      <li className="rounded-lg border p-3 text-sm" data-review-draft={id} data-draft-state="loading" role="status">
        <p className="font-medium">{link?.label ?? "Draft"}</p>
        <p className="text-muted-foreground">Loading the draft…</p>
      </li>
    );
  }
  return (
    <li className="space-y-3 rounded-lg border p-3" data-review-draft={id} data-draft-state={decision ? "decided" : "open"}>
      <header className="space-y-1">
        <h3 className="break-words text-base font-semibold leading-snug">{view.headline}</h3>
        <p className="text-xs text-muted-foreground">
          {view.kindLabel}{view.section ? ` · Section: ${view.section}` : ""} · Proposed by AI · {stateLabel(view.state, false)}
        </p>
      </header>
      {view.dek ? <p className="break-words text-sm" data-draft-dek>{view.dek}</p> : null}
      {view.evidence.length ? (
        <ul aria-label="Evidence" className="space-y-0.5 text-sm" data-draft-evidence>
          {view.evidence.map((line) => <li className="break-words" key={line}><span className="font-medium">Evidence:</span> {line}</li>)}
        </ul>
      ) : null}
      {view.sources.length ? (
        <div className="space-y-1">
          <p className="text-sm font-medium">Sources</p>
          <ul aria-label="Sources" className="space-y-0.5 text-sm" data-draft-sources>
            {view.sources.map((source, index) => (
              <li className="break-words" key={`${source.title}-${index}`}>
                {source.url ? (
                  <a className="inline-flex max-w-full items-center gap-1 text-primary underline underline-offset-4" href={source.url} rel="noreferrer" target="_blank">
                    <span className="break-words">{source.title}</span><ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
                  </a>
                ) : source.title}
                {source.date ? <span className="text-muted-foreground"> ({source.date})</span> : null}
              </li>
            ))}
            {view.moreSources ? <li className="text-muted-foreground">and {view.moreSources} more in the full draft</li> : null}
          </ul>
        </div>
      ) : null}
      <Link className="inline-flex items-center gap-1 text-sm text-primary underline underline-offset-4" data-draft-open href={view.href}>
        Open the full draft in Proposals<ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
      </Link>
      {decision ? (
        <DecidedLine choice={decision.choice} notThisKind={decision.notThisKind} why={decision.why} />
      ) : (
        <div className="space-y-3" data-review-controls>
          <ChoiceButtons chosen={null} disabled={busy || Boolean(hold)} onChoose={(choice) => { if (!busy && !hold) onDecide?.(id, choice, { why: why.trim(), notThisKind }); }} />
          <div aria-live="polite" className="min-h-5 text-sm" role="status">{busy ? "Saving…" : ""}</div>
          {hold ? <p className="text-sm" data-review-disabled-reason>{hold}</p> : null}
          {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
          <WhyBox busy={busy} onChange={setWhy} placeholder="Optional. Write it before you tap Accept or Reject; it is saved with your answer and teaches the AI." value={why} />
          <NotThisKind busy={busy} label={NOT_THIS_KIND.draft} onToggle={() => setNotThisKind((current) => !current)} pressed={notThisKind} />
        </div>
      )}
    </li>
  );
}

function Entry({ request, unread, demo, busy, titles, deleted, drafts, missingDrafts, draftsState, draftErrors, draftBusyId, onAnswer, onMarkRead, onDecideDraft, onRetryDrafts }: {
  request: ReviewRequest; unread: boolean; demo: boolean; busy: boolean; titles: Readonly<Record<string, string>>; deleted: ReadonlySet<string>;
  drafts: Readonly<Record<string, DraftView>>; missingDrafts: ReadonlySet<string>; draftsState: DraftsLoadState; draftErrors: Readonly<Record<string, string>>; draftBusyId: string | null;
  onAnswer?: ViewProps["onAnswer"]; onMarkRead?: ViewProps["onMarkRead"]; onDecideDraft?: ViewProps["onDecideDraft"]; onRetryDrafts?: () => void;
}) {
  const href = subjectHref(request.subject, demo);
  const open = request.state === "open";
  const steering = steeringText(request);
  const draftIds = draftIdsOf(request);
  const draftReview = isDraftReview(request);
  const available = draftIds.filter((id) => !missingDrafts.has(id));
  const Icon = CONTROL_ICON[request.mode];
  // A draft review is decided draft by draft. Only when none of its drafts can be opened here (an idea kept outside Proposals) does the request itself take Accept or Reject.
  const requestLevel = open && (!draftReview || (draftsState === "ready" && available.length === 0));
  const recorded = request.answer?.drafts ?? [];
  return (
    <li className="space-y-3 rounded-lg border p-3" data-review-request={request.id} data-review-mode={request.mode} data-review-state={request.state} data-review-unread={unread || undefined}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline"><Icon aria-hidden="true" className="mr-1 size-3" />{modeLabel(request.mode)}</Badge>
        {unread ? <Badge variant="default"><CircleDotIcon aria-hidden="true" className="mr-1 size-3" />New</Badge> : <span className="text-xs text-muted-foreground">Read</span>}
        <strong className="text-sm">{request.reason}</strong>
      </div>
      <p className="text-xs text-muted-foreground">
        Raised by {request.raisedBy} on {formatWhen(request.raisedAt)}
        {draftReview ? null : <>{" · "}About: {href ? <Link href={href} onClick={() => onMarkRead?.(request.id)}>{subjectLabel(request.subject, titles, deleted)}</Link> : <span>{subjectLabel(request.subject, titles, deleted)}</span>}</>}
      </p>
      {request.ask && !draftReview ? <p className="text-sm">{request.ask}</p> : null}
      {!draftReview && request.links.length ? (
        <ul className="text-xs space-y-0.5" aria-label="Items in this request">
          {request.links.slice(0, 10).map((link, index) => {
            const target = link.url ?? (link.type ? subjectHref({ type: link.type, id: link.id ?? "" }, demo) : null);
            return <li key={`${link.id ?? link.url}-${index}`}>{target ? <Link href={target}>{link.label ?? link.id ?? link.url}</Link> : (link.label ?? link.id)}</li>;
          })}
          {request.links.length > 10 ? <li>and {request.links.length - 10} more</li> : null}
        </ul>
      ) : null}
      {draftReview && open ? (
        <div className="space-y-2">
          <p className="text-sm">Accept or Reject each draft. An accepted draft is approved in Proposals; a rejected one is declined there. Nothing is published by this page.</p>
          {draftsState === "failed" ? (
            <div className="space-y-2" role="alert">
              <p className="text-sm">The drafts could not be loaded right now.</p>
              <Button onClick={onRetryDrafts} size="sm" type="button" variant="outline">Try again</Button>
            </div>
          ) : null}
          <ul aria-label="Drafts in this request" className="space-y-3" data-review-drafts>
            {draftsState === "failed" ? null : available.map((id) => (
              <DraftCard
                busy={draftBusyId === `${request.id}#${id}`} error={draftErrors[`${request.id}#${id}`] ?? null} id={id} key={id} request={request}
                onDecide={(draftId, choice, extras) => onDecideDraft?.(request, draftId, choice, extras)} view={drafts[id]}
              />
            ))}
          </ul>
          {draftIds.length > available.length ? <p className="text-sm text-muted-foreground">{draftIds.length - available.length} of these drafts are not in Proposals on this site, so they cannot be opened here.</p> : null}
        </div>
      ) : null}
      {!open && recorded.length ? (
        <ul aria-label="What you decided" className="space-y-1" data-review-decisions>
          {recorded.map((entry) => (
            <li key={entry.id}>
              <DecidedLine choice={entry.choice} notThisKind={entry.notThisKind} why={entry.why} />
              <Link className="ml-5 text-xs text-primary underline underline-offset-4" href={proposalHref(entry.id, demo)}>{entry.title ?? entry.id}</Link>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-sm" data-review-next>{nextText(request)}</p>
      {steering ? <p className="text-sm" data-review-steering>{steering}</p> : null}
      {requestLevel ? (
        <RequestControls busy={busy} onAnswer={onAnswer} onMarkRead={onMarkRead} request={request} unread={unread} />
      ) : open ? (
        unread ? <Button aria-disabled={busy || undefined} onClick={() => { if (!busy) onMarkRead?.(request.id); }} size="sm" variant="ghost">Mark read</Button> : null
      ) : unread ? (
        <Button aria-disabled={busy || undefined} onClick={() => { if (!busy) onMarkRead?.(request.id); }} size="sm" variant="ghost">Mark read</Button>
      ) : null}
    </li>
  );
}

function CyclotronLine({ entry, held }: { entry: CyclotronEntry; held: boolean }) {
  const confidence = entry.confidence === null ? "confidence not recorded" : `confidence ${Math.round(entry.confidence * 100)}%`;
  return (
    <li className="rounded-lg border p-3 space-y-1" data-cyclotron-entry={entry.lineageId} data-cyclotron-held={held || undefined}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{held ? <HourglassIcon aria-hidden="true" className="mr-1 size-3" /> : <CircleCheckIcon aria-hidden="true" className="mr-1 size-3" />}{held ? "Held for review" : "Decided by the system"}</Badge>
        <strong className="text-sm">{entry.title}</strong>
      </div>
      <p className="text-xs text-muted-foreground">
        Classified as {entry.label} · {confidence}{entry.decidedAt ? ` · ${formatWhen(entry.decidedAt)}` : ""}
        {entry.reviewedByPerson ? " · reviewed by a person" : ""}
      </p>
      {held ? <p className="text-sm">{entry.reviewDetail ? `${entry.reviewDetail}. ` : ""}Held for review: it stays pending until someone decides.</p> : null}
      <Link className="text-sm" href={entry.href}>{held ? "Review it in References" : "Open it in References to correct it"}</Link>
    </li>
  );
}

function Section({ id, title, count, children, empty }: { id: string; title: string; count: number; children: React.ReactNode; empty: string }) {
  return (
    <section aria-labelledby={`notification-${id}`} className="space-y-2" data-notification-section={id}>
      <h2 className="text-sm font-medium" id={`notification-${id}`}>{title} ({count})</h2>
      {count ? children : <p className="text-sm text-muted-foreground">{empty}</p>}
    </section>
  );
}

/** The CMS console home: what needs a person, what will close on its own, and what the system decided. Ignore-safe by design. */
export function NotificationCenterView({
  loadState, requests, readIds, held, autoDecided, demo = false, storyTitles = {}, deletedStories = new Set<string>(), busyId = null, error = null,
  drafts = {}, missingDrafts = new Set<string>(), draftsState = "ready", draftErrors = {}, draftBusyId = null,
  onAnswer, onDecideDraft, onRetryDrafts, onMarkRead, onMarkAllRead,
}: ViewProps) {
  const sections = useMemo(() => sectionReviews(requests), [requests]);
  const unreadCount = requests.filter((request) => isUnread(request, readIds)).length;
  const summary = summarize(sections, held, autoDecided, unreadCount, draftsToDecide(sections.draftBatches, drafts, missingDrafts));
  const entry = (request: ReviewRequest) => (
    <Entry
      busy={busyId === request.id} demo={demo} deleted={deletedStories} draftBusyId={draftBusyId} draftErrors={draftErrors} drafts={drafts} draftsState={draftsState}
      key={request.id} missingDrafts={missingDrafts} onAnswer={onAnswer} onDecideDraft={onDecideDraft} onMarkRead={onMarkRead} onRetryDrafts={onRetryDrafts}
      request={request} titles={storyTitles} unread={isUnread(request, readIds)}
    />
  );
  if (loadState === "loading") return (
    <section aria-label="Loading Notification Center" className="space-y-4" data-notification-state="loading" role="status">
      <div className="h-6 w-48 rounded bg-muted" />
      <div className="h-4 w-3/4 max-w-xl rounded bg-muted" />
      <div className="h-4 w-2/3 max-w-lg rounded bg-muted" />
      <div className="grid gap-3 sm:grid-cols-2">
        {Array.from({ length: 4 }, (_, index) => <div className="h-28 rounded-xl border bg-card p-4" key={index}>
          <div className="h-4 w-2/3 rounded bg-muted" /><div className="mt-4 h-3 w-1/2 rounded bg-muted" />
        </div>)}
      </div>
    </section>
  );
  if (loadState === "forbidden") return <div role="alert" data-notification-state="forbidden"><strong>The Notification Center is for editors and admins</strong></div>;
  if (loadState === "unavailable") return <div role="alert" data-notification-state="unavailable"><strong>Review requests could not be read right now</strong><p>Try again in a minute. The current request state is unknown.</p></div>;
  return (
    <div className="space-y-6" data-notification-center>
      <header className="space-y-1">
        <h1 className="text-lg font-semibold">Notification Center</h1>
        <p className="text-sm" data-notification-summary>{summaryText(summary)}</p>
        <p className="text-xs text-muted-foreground">
          Accept or Reject what you want to decide, and ignore the rest. An AI draft you leave alone stays in Proposals and nothing is published without an editor. A review with a deadline closes when the deadline passes, and flags never wait. Only a hard gate waits for you.
        </p>
        <p className="text-xs text-muted-foreground" data-notification-unread>
          {unreadCount ? `${unreadCount} unread` : "Nothing unread"}
          {unreadCount ? <Button className="ml-2" onClick={onMarkAllRead} size="sm" variant="ghost">Mark all read</Button> : null}
        </p>
        {error ? <p role="alert" className="text-sm" data-notification-error>{error}</p> : null}
      </header>

      <Section count={sections.hardGates.length} empty="No hard gates. Nothing is blocked on you." id="hard-gates" title="Waiting for you: hard gates">
        <ul className="space-y-2">{sections.hardGates.map(entry)}</ul>
      </Section>
      <Section count={sections.draftBatches.length} empty="No AI drafts are waiting for review." id="drafts" title="AI drafts to review">
        <ul className="space-y-3">{sections.draftBatches.map(entry)}</ul>
      </Section>
      <Section count={sections.softReviews.length} empty="No other reviews are open." id="soft-reviews" title="Other reviews, soonest deadline first">
        <ul className="space-y-2">{sections.softReviews.map(entry)}</ul>
      </Section>
      <Section count={held.length} empty="No Cyclotron items are held for review." id="cyclotron" title="Cyclotron items routed to a person (low confidence)">
        <ul className="space-y-2">{held.slice(0, 10).map((item) => <CyclotronLine entry={item} held key={item.lineageId} />)}</ul>
        {held.length > 10 ? <p className="text-sm">and {held.length - 10} more. <Link href={getNewsroomNavHref("/newsroom/references", demo)}>See all in References</Link></p> : null}
      </Section>
      <Section count={sections.flags.length} empty="No flags." id="flags" title="Flags: for your information">
        <ul className="space-y-2">{sections.flags.map(entry)}</ul>
      </Section>
      <Section count={sections.decided.length} empty="Nothing answered or proceeded yet." id="decided" title="Answered, and what became of it">
        <ul className="space-y-2">{sections.decided.slice(0, 20).map(entry)}</ul>
      </Section>
      <details data-notification-section="auto-decided">
        <summary className="cursor-pointer text-sm font-medium">Recently decided by the system ({autoDecided.length})</summary>
        <div className="mt-2 space-y-2">
          <p className="text-xs text-muted-foreground">Read only. The Cyclotron was confident enough to decide these without you. To correct one, open it in References.</p>
          {autoDecided.length ? <ul className="space-y-2">{autoDecided.map((item) => <CyclotronLine entry={item} held={false} key={item.lineageId} />)}</ul> : <p className="text-sm text-muted-foreground">No automatic decisions yet.</p>}
        </div>
      </details>
    </div>
  );
}

/** Everything the container reads and writes. The live one talks to the site's data API; tests pass a fake. */
export type NotificationApi = {
  loadReviews: () => Promise<ReviewLoad>;
  loadDrafts: (ids: string[]) => Promise<DraftLoad>;
  loadStoryTitles: (ids: string[]) => Promise<{ titles: Record<string, string>; deleted: string[] }>;
  answerReviewRequest: (request: ReviewRequest, input: AnswerInput, by: string) => Promise<ReviewRequest>;
  saveDraftDecision: (request: ReviewRequest, draftId: string, decision: DraftDecision) => Promise<ReviewRequest>;
  markReviewRead: (userKey: string, requestId: string) => Promise<void>;
  transitionProposalPath: (proposalId: string, path: readonly string[]) => Promise<ProposalReceipt>;
};

const liveApi: NotificationApi = {
  loadReviews: async () => (await import("../lib/review-client")).loadReviews(),
  loadDrafts: async (ids) => (await import("../lib/review-client")).loadDrafts(ids),
  loadStoryTitles: async (ids) => (await import("../lib/review-client")).loadStoryTitles(ids),
  answerReviewRequest: async (request, input, by) => (await import("../lib/review-client")).answerReviewRequest(request, input, by),
  saveDraftDecision: async (request, draftId, decision) => (await import("../lib/review-client")).saveDraftDecision(request, draftId, decision),
  markReviewRead: async (userKey, requestId) => (await import("../lib/review-client")).markReviewRead(userKey, requestId),
  transitionProposalPath: async (proposalId, path) => (await import("../lib/proposals-client")).transitionProposalPath(proposalId, path),
};

type ContainerProps = {
  references: ReferenceRecord[];
  decisions: ReadonlyMap<string, RelevanceDecisionView>;
  humanCuratedReferenceLineageIds: ReadonlySet<string>;
  actorLabel: string;
  demo: boolean;
  api?: NotificationApi;
};

const REFRESH_MILLISECONDS = 60_000;

export function NotificationCenter({ references, decisions, humanCuratedReferenceLineageIds, actorLabel, demo, api = liveApi }: ContainerProps) {
  const [loadState, setLoadState] = useState<NotificationLoadState>("loading");
  const [requests, setRequests] = useState<ReviewRequest[]>([]);
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [userKey, setUserKey] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [storyTitles, setStoryTitles] = useState<Record<string, string>>({});
  const [deletedStories, setDeletedStories] = useState<ReadonlySet<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, DraftView>>({});
  const [missingDrafts, setMissingDrafts] = useState<ReadonlySet<string>>(new Set());
  const [draftsState, setDraftsState] = useState<DraftsLoadState>("loading");
  const [draftErrors, setDraftErrors] = useState<Record<string, string>>({});
  const [draftBusyId, setDraftBusyId] = useState<string | null>(null);
  const resolving = useRef(new Set<string>());

  const loadDraftsFor = useCallback(async (list: ReviewRequest[]) => {
    const ids = list.filter((request) => request.state === "open" && isDraftReview(request)).flatMap(draftIdsOf);
    if (!ids.length) {
      setDraftsState("ready");
      return;
    }
    if (demo) {
      setDrafts(Object.fromEntries(FIXTURE_DRAFTS.map((row) => [row.id, draftView(row, true)])));
      setMissingDrafts(new Set(ids.filter((id) => !FIXTURE_DRAFTS.some((row) => row.id === id))));
      setDraftsState("ready");
      return;
    }
    try {
      const loaded = await api.loadDrafts(ids);
      setDrafts(loaded.drafts);
      setMissingDrafts(new Set(loaded.missing));
      setDraftsState(loaded.failed.length ? "failed" : "ready");
    } catch {
      setDraftsState("failed");
    }
  }, [api, demo]);

  const refresh = useCallback(async () => {
    if (demo) {
      setRequests(FIXTURE_REVIEW_REQUESTS);
      setReadIds(new Set(["rr-flag-1"]));
      setLoadState("ready");
      void loadDraftsFor(FIXTURE_REVIEW_REQUESTS);
      return;
    }
    try {
      const loaded = await api.loadReviews();
      if (loaded.state !== "ready") {
        setLoadState(loaded.state);
        return;
      }
      setRequests(loaded.requests);
      setReadIds(new Set(loaded.readIds));
      setUserKey(loaded.userKey);
      setLoadState("ready");
      void loadDraftsFor(loaded.requests);
      const stories = await api.loadStoryTitles(loaded.requests.filter((request) => request.subject.type === "story").map((request) => request.subject.id)).catch(() => ({ titles: {}, deleted: [] as string[] }));
      setStoryTitles(stories.titles);
      setDeletedStories(new Set(stories.deleted));
    } catch {
      setLoadState("unavailable");
    }
  }, [api, demo, loadDraftsFor]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MILLISECONDS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const held = useMemo(() => cyclotronHeldForReview(references, decisions, demo), [references, decisions, demo]);
  const autoDecided = useMemo(() => cyclotronAutoDecided(references, decisions, humanCuratedReferenceLineageIds, demo), [references, decisions, humanCuratedReferenceLineageIds, demo]);

  const markRead = useCallback(async (requestId: string) => {
    setReadIds((current) => new Set(current).add(requestId));
    if (demo || !userKey) return;
    await api.markReviewRead(userKey, requestId).catch(() => undefined);
  }, [api, demo, userKey]);

  const answer = useCallback(async (request: ReviewRequest, input: AnswerInput) => {
    setError(null);
    setBusyId(request.id);
    try {
      if (demo) throw new Error("This is a demo: answers are not saved.");
      const saved = await api.answerReviewRequest(request, input, actorLabel);
      setRequests((current) => current.map((entry) => (entry.id === saved.id ? saved : entry)));
      await markRead(request.id);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save the answer.");
    } finally {
      setBusyId(null);
    }
  }, [actorLabel, api, demo, markRead]);

  /** Accept or Reject one draft: the Proposal moves to approved or declined, the decision is recorded on the request, and the request closes once every draft is decided. */
  const decideDraft = useCallback(async (request: ReviewRequest, draftId: string, choice: DraftChoice, extras: DraftExtras) => {
    const key = `${request.id}#${draftId}`;
    setDraftErrors(({ [key]: _gone, ...rest }) => rest);
    setDraftBusyId(key);
    resolving.current.add(request.id);
    try {
      if (demo) throw new Error("This is a demo: decisions are not saved.");
      const view = drafts[draftId];
      if (!view) throw new Error("This draft has not loaded yet.");
      const path = choice === "accept" ? acceptPath(view.state) : rejectPath(view.state);
      if (!path) throw new Error(`This draft is ${stateLabel(view.state, false).toLowerCase()} and cannot be ${choice === "accept" ? "accepted" : "rejected"} from here. Open it in Proposals.`);
      const receipt = await api.transitionProposalPath(draftId, path);
      if (receipt.status !== "ok") throw new Error(proposalReceiptMessage(receipt));
      const decided: DraftView = { ...view, state: choice === "accept" ? "approved" : "declined", decided: choice };
      const nextDrafts = { ...drafts, [draftId]: decided };
      setDrafts(nextDrafts);
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
      setDraftErrors((current) => ({ ...current, [key]: failure instanceof Error ? failure.message : "Could not save the decision." }));
      if (!demo) void loadDraftsFor([request]);
    } finally {
      resolving.current.delete(request.id);
      setDraftBusyId(null);
    }
  }, [actorLabel, api, demo, drafts, loadDraftsFor, markRead]);

  // Drafts decided in Proposals (not here) still close their request.
  useEffect(() => {
    if (demo || draftsState !== "ready") return;
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
  }, [api, demo, drafts, draftsState, requests]);

  const markAllRead = useCallback(() => {
    for (const request of requests) if (isUnread(request, readIds)) void markRead(request.id);
  }, [markRead, readIds, requests]);

  return (
    <NotificationCenterView
      autoDecided={autoDecided} busyId={busyId} storyTitles={storyTitles} deletedStories={deletedStories} demo={demo} draftBusyId={draftBusyId} draftErrors={draftErrors}
      drafts={drafts} draftsState={draftsState} error={error} held={held} loadState={loadState} missingDrafts={missingDrafts}
      onAnswer={answer} onDecideDraft={(request, draftId, choice, extras) => void decideDraft(request, draftId, choice, extras)}
      onMarkAllRead={markAllRead} onMarkRead={markRead} onRetryDrafts={() => void loadDraftsFor(requests)} readIds={readIds} requests={requests}
    />
  );
}
