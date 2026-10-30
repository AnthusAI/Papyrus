"use client";

import { BookmarkIcon, ExternalLinkIcon, GlobeIcon, LinkIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { referenceRoleLabel, storyMessageFeed, storyReportingTrailIsEmpty, type StoryReportingTrail, type TrailReference } from "../lib/story-reporting-trail";
import { loadStoryReportingTrail } from "./story-reporting-trail-client";

const timestampFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : timestampFormat.format(parsed);
}

function ReferenceSummary({ citedKeys, demo, focused, reference }: { citedKeys: readonly string[]; demo: boolean; focused: boolean; reference: TrailReference }) {
  const basedOn = reference.role === "based_on";
  const RoleIcon = basedOn ? LinkIcon : BookmarkIcon;
  return <div className="story-trail-reference" data-story-trail-reference-card={reference.referenceId}>
    {/* eslint-disable-next-line @next/next/no-img-element -- the preview is shown from its own site, never copied or optimised here */}
    {reference.previewImageUrl && <img alt="" className="story-trail-reference-image" data-story-trail-reference-image loading="lazy" referrerPolicy="no-referrer" src={reference.previewImageUrl} />}
    <div className="story-trail-reference-text">
      <div className="story-trail-row">
        <strong data-story-trail-reference-title>{reference.title ?? reference.referenceId}</strong>
        <span className="story-trail-role" data-story-trail-reference-role={reference.role}><RoleIcon aria-hidden="true" size={13} />{referenceRoleLabel(reference.role)}</span>
        {reference.citationKey && citedKeys.includes(reference.citationKey) && <span className="story-trail-role">In the text</span>}
      </div>
      {reference.siteName && <div className="story-trail-meta" data-story-trail-reference-site><GlobeIcon aria-hidden="true" size={13} /> {reference.siteName}</div>}
      <div className="story-trail-meta">{[reference.addedBy && `added by ${reference.addedBy}`, formatTimestamp(reference.addedAt), reference.citationKey && `citation key ${reference.citationKey}`].filter(Boolean).join(" · ")}</div>
      {reference.note && <p data-story-trail-reference-summary={focused ? "focused" : undefined}>{reference.note}</p>}
      <div className="story-trail-reference-links">
        {reference.referenceLineageId && <Link data-story-trail-open-reference={reference.referenceLineageId} href={getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(reference.referenceLineageId)}`, demo)}><BookmarkIcon aria-hidden="true" size={14} /> Open the Reference</Link>}
        {reference.sourceUri && <a href={reference.sourceUri} rel="noreferrer" target="_blank"><ExternalLinkIcon aria-hidden="true" size={14} /> Open the source page</a>}
      </div>
    </div>
  </div>;
}

function TrailSection({ count, children, title }: { count: number; children: React.ReactNode; title: string }) {
  return <section className="story-trail-section" data-story-trail-section={title.toLowerCase()}>
    <h3>{title} <small>{count}</small></h3>
    {count ? children : <p className="story-trail-empty">None recorded.</p>}
  </section>;
}

/**
 * The messages and references of one story: draft versions, the assignments and agent events that did the work,
 * notes and packets, the references behind it, and attached files. Container queries lay the sections out
 * in one column in a narrow Board panel and side by side on a wide page.
 */
export function StoryReportingTrailView({ citedKeys = [], demo = false, focusedReferenceId = null, itemId, lineageId, onOpenVersion, onShowReference, view = "messages" }: { citedKeys?: readonly string[]; demo?: boolean; focusedReferenceId?: string | null; itemId: string; lineageId: string | null | undefined; onOpenVersion?: (versionId: string) => void; onShowReference?: (referenceId: string) => void; view?: "messages" | "references" }) {
  const [trail, setTrail] = useState<StoryReportingTrail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setTrail(null); setError(null);
    loadStoryReportingTrail(lineageId || itemId, itemId, demo)
      .then(loaded => { if (!cancelled) setTrail(loaded); })
      .catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load the reporting trail."); });
    return () => { cancelled = true; };
  }, [demo, itemId, lineageId]);
  if (error) return <p role="alert" className="story-trail-empty">{error}</p>;
  if (!trail) return <p className="story-trail-empty">Loading the reporting trail…</p>;
  const messageFeed = storyMessageFeed(trail);
  if (view === "references") return <div className="story-trail" data-story-trail data-story-trail-view="references">
    <TrailSection count={trail.references.length} title="References">
      {trail.references.some(reference => reference.role === "based_on") && <p className="story-trail-meta" data-story-trail-based-on-note>The text of this story is our own. It is based on the Reference marked Based on, and is written and edited here, never copied from it.</p>}
      <ul className="story-trail-list" data-story-references-list>
        {trail.references.map(reference => <li data-story-reference-entry={reference.referenceId} data-story-reference-focused={reference.referenceId === focusedReferenceId ? "true" : undefined} key={reference.relationId} ref={reference.referenceId === focusedReferenceId ? node => node?.scrollIntoView({ block: "nearest" }) : undefined}>
          <ReferenceSummary citedKeys={citedKeys} demo={demo} focused={reference.referenceId === focusedReferenceId} reference={reference} />
        </li>)}
      </ul>
    </TrailSection>
  </div>;
  return <div className="story-trail" data-story-trail data-story-trail-view="messages">
    {storyReportingTrailIsEmpty(trail) && <p className="story-trail-empty">No messages have been recorded for this story yet. Notes and packets, the work done on it, its draft versions and the references behind it appear here as agents and editors work on it.</p>}
    <TrailSection count={messageFeed.length} title="Messages">
      <ol className="story-trail-list" data-story-trail-feed>
        {messageFeed.map(entry => entry.entryKind === "reference"
          ? <li data-story-trail-feed-reference={entry.reference.referenceId} key={entry.id}>
            <div className="story-trail-row"><span className="story-trail-chip">Reference found</span><span className="story-trail-meta">{formatTimestamp(entry.createdAt)}</span></div>
            <ReferenceSummary citedKeys={citedKeys} demo={demo} focused={false} reference={entry.reference} />
            {onShowReference && <button className="newsroom-article-link-button" data-story-trail-show-reference={entry.reference.referenceId} onClick={() => onShowReference(entry.reference.referenceId)} type="button">Show in the References list</button>}
          </li>
          : <li key={entry.id}>
            <div className="story-trail-row"><strong>{entry.authorLabel ?? "Unknown author"}</strong>{entry.messageKind && <span className="story-trail-chip">{entry.messageKind.replace(/_/g, " ")}</span>}<span className="story-trail-meta">{formatTimestamp(entry.createdAt)}</span></div>
            {entry.summary && <p><strong>{entry.summary}</strong></p>}
            {entry.content && <details className="story-trail-message" open={messageFeed.length <= 3}><summary>Show the message</summary><pre>{entry.content}</pre></details>}
          </li>)}
      </ol>
    </TrailSection>
    {trail.stageMoves.length > 0 && <TrailSection count={trail.stageMoves.length} title="Stage moves">
      <ol className="story-trail-list" data-story-trail-stage-moves>
        {[...trail.stageMoves].reverse().map(move => <li key={`${move.at}-${move.to}`}>
          <div className="story-trail-row"><strong>{move.from ?? "start"} → {move.to}</strong>{move.by && <span className="story-trail-chip">{move.by}</span>}<span className="story-trail-meta">{formatTimestamp(move.at)}</span></div>
          {move.reason && <p className="story-trail-meta">{move.reason}</p>}
        </li>)}
      </ol>
    </TrailSection>}
    <TrailSection count={trail.versions.length} title="Draft versions">
      <ol className="story-trail-list">
        {trail.versions.map((version, versionIndex) => <li key={version.id}>
          <div className="story-trail-row"><strong>Version {version.versionNumber}</strong>{versionIndex === 0 && <span className="story-trail-chip">Latest</span>}<span className="story-trail-chip">{version.versionState ?? "draft"}</span>{version.stage && <span className="story-trail-chip">{version.stage}</span>}</div>
          <div className="story-trail-meta">{[formatTimestamp(version.versionCreatedAt ?? version.updatedAt), version.versionCreatedBy, version.changeReason].filter(Boolean).join(" · ")}</div>
          {onOpenVersion
            ? <button className="newsroom-article-link-button" data-story-trail-open-version={version.versionNumber} onClick={() => onOpenVersion(version.id)} type="button">{versionIndex === 0 ? "Open the latest version" : "Open this older version (read-only)"}</button>
            : <Link href={getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(version.id)}`, demo)}>{versionIndex === 0 ? "Open the latest version" : "Open this older version (read-only)"}</Link>}
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
    <TrailSection count={trail.attachments.length} title="Files">
      <ul className="story-trail-list">
        {trail.attachments.map(attachment => <li key={attachment.id}><strong>{attachment.filename ?? attachment.id}</strong> <span className="story-trail-meta">{[attachment.role, attachment.mediaType].filter(Boolean).join(" · ")}</span></li>)}
      </ul>
    </TrailSection>
  </div>;
}
