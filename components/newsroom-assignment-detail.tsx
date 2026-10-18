"use client";

import Link from "next/link";
import type { AssignmentRecord } from "../lib/category-repository";

const assignmentDateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function formattedTimestamp(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : assignmentDateFormat.format(parsed);
}

type DetailField = { label: string; value: string | null | undefined };

/**
 * The whole assignment, laid out by container width: one column in a narrow Board panel, labelled
 * columns when the container is wide, such as the dedicated page on a large monitor.
 */
export function NewsroomAssignmentDetail({ assignment, pageHref, showTitle = true }: { assignment: AssignmentRecord; pageHref?: string; showTitle?: boolean }) {
  const facts: DetailField[] = [
    { label: "Status", value: assignment.status },
    { label: "Type", value: assignment.assignmentTypeKey },
    { label: "Assignee", value: assignment.assigneeId ?? assignment.assigneeKey },
    { label: "Section", value: assignment.sectionKey },
    { label: "Created", value: formattedTimestamp(assignment.createdAt) },
    { label: "Updated", value: formattedTimestamp(assignment.updatedAt) },
    { label: "Completed", value: formattedTimestamp(assignment.completedAt) },
  ].filter(field => field.value);
  const prose: DetailField[] = [
    { label: "Summary", value: assignment.summary },
    { label: "Brief", value: assignment.brief },
    { label: "Instructions", value: assignment.instructions },
  ].filter(field => field.value);
  return <article className="newsroom-assignment-detail">
    {showTitle && <h2 className="newsroom-assignment-detail-title">{assignment.title}</h2>}
    <dl className="newsroom-assignment-detail-facts">
      {facts.map(field => <div key={field.label}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}
    </dl>
    <div className="newsroom-assignment-detail-prose">
      {prose.map(field => <section key={field.label}><h3>{field.label}</h3><p>{field.value}</p></section>)}
    </div>
    {pageHref && <Link className="organizer-header-button" href={pageHref}>Open full page</Link>}
  </article>;
}
