"use client";

import Link from "next/link";
import { useState } from "react";
import type { AssignmentRecord } from "../lib/category-repository";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";

export type AssignmentDeskOption = { value: string; label: string; kind: "core" | "rotating" };
const NO_DESK_VALUE = "__no-desk__";

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
export function NewsroomAssignmentDetail({ assignment, deskOptions = [], onDeskChange, pageHref, showTitle = true }: {
  assignment: AssignmentRecord;
  deskOptions?: AssignmentDeskOption[];
  onDeskChange?: (deskId: string | null) => Promise<void>;
  pageHref?: string;
  showTitle?: boolean;
}) {
  const [deskError, setDeskError] = useState<string | null>(null);
  const [savingDesk, setSavingDesk] = useState(false);
  const currentDesk = assignment.sectionId || assignment.sectionKey || "";
  const deskChoices = deskOptions;
  const changeDesk = (value: string) => {
    if (!onDeskChange) return;
    setSavingDesk(true); setDeskError(null);
    onDeskChange(value === NO_DESK_VALUE ? null : value).catch((reason: unknown) => setDeskError(reason instanceof Error ? reason.message : "Could not save the section.")).finally(() => setSavingDesk(false));
  };
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
    {onDeskChange && <label className="newsroom-assignment-detail-desk">
      <span>Section</span>
      <Select onValueChange={(value) => { if (typeof value === "string") changeDesk(value); }} value={deskChoices.some(option => option.value === currentDesk) ? currentDesk : NO_DESK_VALUE} disabled={savingDesk}>
        <SelectTrigger aria-label="Section" className="w-full" data-newsroom-assignment-desk>
          <SelectValue>{deskChoices.find(option => option.value === currentDesk)?.label ?? "No section"}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_DESK_VALUE}>No section</SelectItem>
          {(["core", "rotating"] as const).map(kind => deskChoices.some(option => option.kind === kind) ? <SelectGroup key={kind}><SelectLabel>{kind === "core" ? "Core sections" : "Rotating sections"}</SelectLabel>{deskChoices.filter(option => option.kind === kind).map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectGroup> : null)}
        </SelectContent>
      </Select>
      {currentDesk && !deskChoices.some(option => option.value === currentDesk) ? <small className="newsroom-desk-legacy-value">Old section value: {currentDesk}</small> : null}
      {deskError && <p role="alert" className="newsroom-assignment-detail-error">{deskError}</p>}
    </label>}
    <div className="newsroom-assignment-detail-prose">
      {prose.map(field => <section key={field.label}><h3>{field.label}</h3><p>{field.value}</p></section>)}
    </div>
    {pageHref && <Link className="organizer-header-button" href={pageHref}>Open full page</Link>}
  </article>;
}
