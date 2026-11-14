import Link from "next/link";
import { CalendarClock, PlusIcon } from "lucide-react";
import { newsroomHref } from "../lib/newsroom-base-path";
import { getContentItemName } from "../lib/site-brand";
import { getNewsroomNavHref } from "../lib/newsroom-nav";

export type NewsroomBoardPresentation = "board" | "list";

/** The board page's header controls: the Board and List toggle, the loaded-record note, and a new-item link when the board lists content items. */
export function NewsroomBoardHeaderActions({ view, onViewChange, recordCount, showsNewContentItemLink }: {
  view: NewsroomBoardPresentation;
  onViewChange: (view: NewsroomBoardPresentation) => void;
  recordCount: number | null;
  showsNewContentItemLink: boolean;
}) {
  const newContentItemLabel = `New ${getContentItemName().singular.toLowerCase()}`;
  return <>
    {recordCount !== null ? <span role="status" className="organizer-board-note">{recordCount} records loaded.</span> : null}
    <div role="group" aria-label="Record presentation" className="organizer-board-view-toggle"><button type="button" className="organizer-header-button" aria-pressed={view === "board"} onClick={() => onViewChange("board")}>Board</button><button type="button" className="organizer-header-button" aria-pressed={view === "list"} onClick={() => onViewChange("list")}>List</button></div>
    {showsNewContentItemLink && (
      <Link className="organizer-header-button" data-newsroom-schedule-link href={getNewsroomNavHref(newsroomHref("schedule"))}>
        <CalendarClock size={14} aria-hidden="true" />
        <span className="organizer-header-button-label">Schedule</span>
      </Link>
    )}
    {showsNewContentItemLink && (
      <Link className="organizer-header-button" data-newsroom-article-new href={getNewsroomNavHref(newsroomHref("articles", "new"))} aria-label={newContentItemLabel}>
        <PlusIcon size={14} aria-hidden="true" />
        <span className="organizer-header-button-label">{newContentItemLabel}</span>
      </Link>
    )}
  </>;
}
