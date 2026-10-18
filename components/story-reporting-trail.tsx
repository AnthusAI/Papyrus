"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { storyReportingTrailIsEmpty, type StoryReportingTrail } from "../lib/story-reporting-trail";
import { loadStoryReportingTrail } from "./story-reporting-trail-client";

const timestampFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : timestampFormat.format(parsed);
}

function TrailSection({ count, children, title }: { count: number; children: React.ReactNode; title: string }) {
  return <section className="story-trail-section" data-story-trail-section={title.toLowerCase()}>
    <h3>{title} <small>{count}</small></h3>
    {count ? children : <p className="story-trail-empty">None recorded.</p>}
  </section>;
}

/**
 * The reporting trail of one story: draft versions, the assignments and agent events that did the work,
 * notes and packets, the references behind it, and attached files. Container queries lay the sections out
 * in one column in a narrow Board panel and side by side on a wide page.
 */
export function StoryReportingTrailView({ demo = false, itemId, lineageId }: { demo?: boolean; itemId: string; lineageId: string | null | undefined }) {
  const [trail, setTrail] = useState<StoryReportingTrail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setTrail(null); setError(null);
    loadStoryReportingTrail(lineageId || itemId, itemId)
      .then(loaded => { if (!cancelled) setTrail(loaded); })
      .catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load the reporting trail."); });
    return () => { cancelled = true; };
  }, [itemId, lineageId]);
  if (error) return <p role="alert" className="story-trail-empty">{error}</p>;
  if (!trail) return <p className="story-trail-empty">Loading the reporting trail…</p>;
  return <div className="story-trail" data-story-trail>
    {storyReportingTrailIsEmpty(trail) && <p className="story-trail-empty">No reporting trail has been recorded for this story yet. Research, reporting and copywriting assignments, their notes and packets, and the references behind the story appear here as agents and editors work on it.</p>}
    <TrailSection count={trail.versions.length} title="Draft versions">
      <ol className="story-trail-list">
        {trail.versions.map(version => <li key={version.id}>
          <div className="story-trail-row"><strong>Version {version.versionNumber}</strong> <span className="story-trail-chip">{version.versionState ?? "draft"}</span>{version.stage && <span className="story-trail-chip">{version.stage}</span>}</div>
          <div className="story-trail-meta">{[formatTimestamp(version.versionCreatedAt ?? version.updatedAt), version.versionCreatedBy, version.changeReason].filter(Boolean).join(" · ")}</div>
          <Link href={getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(version.id)}`, demo)}>Open this version</Link>
        </li>)}
      </ol>
    </TrailSection>
    <TrailSection count={trail.assignments.length} title="Work">
      <ol className="story-trail-list">
        {trail.assignments.map(assignment => <li key={assignment.id}>
          <div className="story-trail-row"><strong>{assignment.title}</strong> <span className="story-trail-chip">{assignment.status}</span></div>
          <div className="story-trail-meta">{[assignment.assignmentTypeKey, assignment.assigneeKey, formatTimestamp(assignment.createdAt)].filter(Boolean).join(" · ")}</div>
          {assignment.summary && <p>{assignment.summary}</p>}
          {assignment.events.length > 0 && <ol className="story-trail-events">
            {assignment.events.map(event => <li key={event.id}>
              <span className="story-trail-meta">{formatTimestamp(event.createdAt)}</span> {event.eventType}{event.toStatus ? ` → ${event.toStatus}` : ""}{event.actorLabel ? ` by ${event.actorLabel}` : ""}{event.note ? `: ${event.note}` : ""}
            </li>)}
          </ol>}
          <Link href={getNewsroomNavHref(`/newsroom/assignments/${encodeURIComponent(assignment.id)}`, demo)}>Open assignment</Link>
        </li>)}
      </ol>
    </TrailSection>
    <TrailSection count={trail.threads.length} title="Notes and packets">
      <ol className="story-trail-list">
        {trail.threads.map(thread => <li key={thread.id}>
          <div className="story-trail-row"><strong>{thread.title ?? thread.threadKind ?? "Thread"}</strong></div>
          {thread.summary && <p>{thread.summary}</p>}
          {thread.messages.map(message => <details key={message.id} className="story-trail-message">
            <summary>{[message.messageKind, message.authorLabel, formatTimestamp(message.createdAt)].filter(Boolean).join(" · ") || "Message"}{message.summary ? ` — ${message.summary}` : ""}</summary>
            <pre>{message.content}</pre>
          </details>)}
        </li>)}
      </ol>
    </TrailSection>
    <TrailSection count={trail.references.length} title="References">
      <ul className="story-trail-list">
        {trail.references.map(reference => <li key={reference.relationId}>
          <div className="story-trail-row"><strong>{reference.title ?? reference.referenceId}</strong> <span className="story-trail-chip">{reference.predicate}</span></div>
          {reference.referenceLineageId && <Link href={getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(reference.referenceLineageId)}`, demo)}>Open reference</Link>}
        </li>)}
      </ul>
    </TrailSection>
    <TrailSection count={trail.attachments.length} title="Files">
      <ul className="story-trail-list">
        {trail.attachments.map(attachment => <li key={attachment.id}><strong>{attachment.filename ?? attachment.id}</strong> <span className="story-trail-meta">{[attachment.role, attachment.mediaType].filter(Boolean).join(" · ")}</span></li>)}
      </ul>
    </TrailSection>
  </div>;
}
