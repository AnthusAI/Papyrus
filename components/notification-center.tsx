"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import {
  cyclotronAutoDecided, cyclotronHeldForReview, formatWhen, isUnread, modeLabel, modeMark, nextText, sectionReviews,
  steeringText, subjectHref, subjectLabel, summarize, summaryText,
  type AnswerInput, type CyclotronEntry, type ReviewRequest,
} from "../lib/review-requests";
import type { ReferenceRecord } from "../lib/category-repository";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { FIXTURE_REVIEW_REQUESTS } from "../lib/review-fixture";

export type NotificationLoadState = "loading" | "ready" | "forbidden" | "unavailable";

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
  onAnswer?: (request: ReviewRequest, input: AnswerInput) => void;
  onMarkRead?: (requestId: string) => void;
  onMarkAllRead?: () => void;
};

function Entry({ request, unread, demo, busy, titles, deleted, onAnswer, onMarkRead }: {
  request: ReviewRequest; unread: boolean; demo: boolean; busy: boolean; titles: Readonly<Record<string, string>>; deleted: ReadonlySet<string>;
  onAnswer?: ViewProps["onAnswer"]; onMarkRead?: ViewProps["onMarkRead"];
}) {
  const [note, setNote] = useState("");
  const href = subjectHref(request.subject, demo);
  const open = request.state === "open";
  const steering = steeringText(request);
  const act = (input: AnswerInput) => onAnswer?.(request, { ...input, feedback: input.feedback ?? (note.trim() || null) });
  return (
    <li className="rounded-lg border p-3 space-y-2" data-review-request={request.id} data-review-mode={request.mode} data-review-state={request.state} data-review-unread={unread || undefined}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline"><span aria-hidden="true">{modeMark(request.mode)} </span>{modeLabel(request.mode)}</Badge>
        {unread ? <Badge variant="default"><span aria-hidden="true">● </span>New</Badge> : <span className="text-xs text-muted-foreground">Read</span>}
        <strong className="text-sm">{request.reason}</strong>
      </div>
      <p className="text-xs text-muted-foreground">
        Raised by {request.raisedBy} on {formatWhen(request.raisedAt)}
        {" · "}About: {href ? <Link href={href} onClick={() => onMarkRead?.(request.id)}>{subjectLabel(request.subject, titles, deleted)}</Link> : <span>{subjectLabel(request.subject, titles, deleted)}</span>}
      </p>
      {request.ask ? <p className="text-sm">{request.ask}</p> : null}
      {request.links.length ? (
        <ul className="text-xs space-y-0.5" aria-label="Items in this request">
          {request.links.slice(0, 10).map((link, index) => {
            const target = link.url ?? (link.type ? subjectHref({ type: link.type, id: link.id ?? "" }, demo) : null);
            return <li key={`${link.id ?? link.url}-${index}`}>{target ? <Link href={target}>{link.label ?? link.id ?? link.url}</Link> : (link.label ?? link.id)}</li>;
          })}
          {request.links.length > 10 ? <li>and {request.links.length - 10} more</li> : null}
        </ul>
      ) : null}
      <p className="text-sm" data-review-next>{nextText(request)}</p>
      {steering ? <p className="text-sm" data-review-steering>{steering}</p> : null}
      {open ? (
        <div className="space-y-2" data-review-controls>
          <label className="block text-xs text-muted-foreground">
            Steering note (optional)
            <textarea
              className="mt-1 block w-full rounded-md border bg-background p-2 text-sm"
              disabled={busy}
              onChange={(event) => setNote(event.target.value)}
              placeholder={request.mode === "flag" ? "Tell the step what to do differently" : "What should change, or what did you want instead?"}
              rows={2}
              value={note}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            {request.mode === "flag" ? (
              <Button disabled={busy} onClick={() => act({ decision: "acknowledge" })} size="sm" variant="outline">Acknowledge</Button>
            ) : (
              <>
                <Button disabled={busy} onClick={() => act({ decision: "approve" })} size="sm" variant="outline">Approve</Button>
                <Button disabled={busy} onClick={() => act({ decision: "reject" })} size="sm" variant="outline">Reject</Button>
              </>
            )}
            <Button disabled={busy || !note.trim()} onClick={() => act({ decision: "feedback", steer: "adjust" })} size="sm" variant="outline">Steer with this note</Button>
            <Button disabled={busy} onClick={() => act({ decision: "feedback", steer: "not_this_kind" })} size="sm" variant="outline">Not this kind of thing</Button>
            {unread ? <Button disabled={busy} onClick={() => onMarkRead?.(request.id)} size="sm" variant="ghost">Mark read</Button> : null}
          </div>
        </div>
      ) : unread ? (
        <Button disabled={busy} onClick={() => onMarkRead?.(request.id)} size="sm" variant="ghost">Mark read</Button>
      ) : null}
    </li>
  );
}

function CyclotronLine({ entry, held }: { entry: CyclotronEntry; held: boolean }) {
  const confidence = entry.confidence === null ? "confidence not recorded" : `confidence ${Math.round(entry.confidence * 100)}%`;
  return (
    <li className="rounded-lg border p-3 space-y-1" data-cyclotron-entry={entry.lineageId} data-cyclotron-held={held || undefined}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline"><span aria-hidden="true">{held ? "◔" : "✓"} </span>{held ? "Held for review" : "Decided by the system"}</Badge>
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

/** The CMS console home: what needs a person, what will proceed on its own, and what the system decided. Ignore-safe by design. */
export function NotificationCenterView({ loadState, requests, readIds, held, autoDecided, demo = false, storyTitles = {}, deletedStories = new Set<string>(), busyId = null, error = null, onAnswer, onMarkRead, onMarkAllRead }: ViewProps) {
  const sections = useMemo(() => sectionReviews(requests), [requests]);
  const unreadCount = requests.filter((request) => isUnread(request, readIds)).length;
  const summary = summarize(sections, held, autoDecided, unreadCount);
  const entry = (request: ReviewRequest) => (
    <Entry busy={busyId === request.id} demo={demo} key={request.id} titles={storyTitles} deleted={deletedStories} onAnswer={onAnswer} onMarkRead={onMarkRead} request={request} unread={isUnread(request, readIds)} />
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
          Look, or steer. Anything you ignore keeps going: soft reviews proceed at their deadline and flags never wait. Only a hard gate waits for you.
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
      <Section count={sections.softReviews.length} empty="No soft reviews are running." id="soft-reviews" title="Proceeding soon: soft reviews, soonest deadline first">
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

type ContainerProps = {
  references: ReferenceRecord[];
  decisions: ReadonlyMap<string, RelevanceDecisionView>;
  humanCuratedReferenceLineageIds: ReadonlySet<string>;
  actorLabel: string;
  demo: boolean;
};

const REFRESH_MILLISECONDS = 60_000;

export function NotificationCenter({ references, decisions, humanCuratedReferenceLineageIds, actorLabel, demo }: ContainerProps) {
  const [loadState, setLoadState] = useState<NotificationLoadState>("loading");
  const [requests, setRequests] = useState<ReviewRequest[]>([]);
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [userKey, setUserKey] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [storyTitles, setStoryTitles] = useState<Record<string, string>>({});
  const [deletedStories, setDeletedStories] = useState<ReadonlySet<string>>(new Set());

  const refresh = useCallback(async () => {
    if (demo) {
      setRequests(FIXTURE_REVIEW_REQUESTS);
      setReadIds(new Set(["rr-flag-1"]));
      setLoadState("ready");
      return;
    }
    try {
      const { loadReviews } = await import("../lib/review-client");
      const loaded = await loadReviews();
      if (loaded.state !== "ready") {
        setLoadState(loaded.state);
        return;
      }
      setRequests(loaded.requests);
      setReadIds(new Set(loaded.readIds));
      setUserKey(loaded.userKey);
      setLoadState("ready");
      const { loadStoryTitles } = await import("../lib/review-client");
      const stories = await loadStoryTitles(loaded.requests.filter((request) => request.subject.type === "story").map((request) => request.subject.id)).catch(() => ({ titles: {}, deleted: [] as string[] }));
      setStoryTitles(stories.titles);
      setDeletedStories(new Set(stories.deleted));
    } catch {
      setLoadState("unavailable");
    }
  }, [demo]);

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
    const { markReviewRead } = await import("../lib/review-client");
    await markReviewRead(userKey, requestId).catch(() => undefined);
  }, [demo, userKey]);

  const answer = useCallback(async (request: ReviewRequest, input: AnswerInput) => {
    setError(null);
    setBusyId(request.id);
    try {
      if (demo) throw new Error("This is a demo: answers are not saved.");
      const { answerReviewRequest } = await import("../lib/review-client");
      const saved = await answerReviewRequest(request, input, actorLabel);
      setRequests((current) => current.map((entry) => (entry.id === saved.id ? saved : entry)));
      await markRead(request.id);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save the answer.");
    } finally {
      setBusyId(null);
    }
  }, [actorLabel, demo, markRead]);

  const markAllRead = useCallback(() => {
    for (const request of requests) if (isUnread(request, readIds)) void markRead(request.id);
  }, [markRead, readIds, requests]);

  return (
    <NotificationCenterView
      autoDecided={autoDecided} busyId={busyId} storyTitles={storyTitles} deletedStories={deletedStories} demo={demo} error={error} held={held} loadState={loadState}
      onAnswer={answer} onMarkAllRead={markAllRead} onMarkRead={markRead} readIds={readIds} requests={requests}
    />
  );
}
