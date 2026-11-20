"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarClock, TriangleAlert, Undo2 } from "lucide-react";
import "./newsroom-theme";
import { canReadNewsroomBoard, contentItemBoardPathSegment } from "../lib/newsroom-board";
import { displayNewsroomSectionShortTitle } from "../lib/newsroom-sections";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { newsroomHref } from "../lib/newsroom-base-path";
import { SITE_BRAND } from "../lib/site-brand";
import { useScheduleZone } from "../lib/schedule-zone";
import { formatScheduleTime, scheduleFromFields, scheduleWording, zoneCity } from "../lib/story-schedule";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { resolveArticlesBackend } from "../lib/newsroom-articles";
import type { PublishedStoryRow } from "../lib/story-schedule-query";
import type { ContentItemVersionRecord } from "../lib/content-item-lifecycle";
import type { NewsroomSectionRecord } from "../lib/category-repository";
import { loadNewsroomPublishedStories, loadNewsroomScheduledStories } from "./news-desk-taxonomy-client";
import { NewsDeskAccessGate } from "./newsroom-access-gate";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { NewsroomOpsShell, NewsroomOpsStatusBanner } from "./newsroom-ops-shell";
import { SCHEDULE_ITEM_ICONS, canDrag, type RescheduleOutcome, type ScheduleCalendarItem, type ScheduleView } from "./schedule-calendar";

/** FullCalendar is about 80 kB; it loads here and nowhere else. */
const ScheduleCalendar = dynamic(() => import("./schedule-calendar"), {
  ssr: false,
  loading: () => <p className="schedule-zone-note" role="status">Loading the calendar…</p>,
});

const STATE_WORD = { scheduled: "Scheduled", overdue: "Overdue", superseded: "Superseded" } as const;
/** The backend's own words for a time that has passed; the drop is refused here first, so nothing is sent. */
const PAST_DROP_MESSAGE = "That time has passed.";
type Notice = { tone: "done" | "problem"; text: string; undo?: () => void };
const EMPTY_TEXT: Record<ScheduleView, string> = { day: "Nothing is scheduled today.", week: "Nothing is scheduled this week.", month: "Nothing is scheduled this month." };

/** A phone shows the lists: the seven-day grid does not fit 375 pixels. */
function usePhone(): boolean | null {
  const [phone, setPhone] = useState<boolean | null>(null);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)");
    const update = () => setPhone(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return phone;
}

/**
 * The Schedule page: the Stories that are scheduled, overdue or superseded, and the ones published in the same range, by day, week or month in the publication's
 * time zone, with a plain list of the same items under the calendar for keyboard and screen-reader use. It reads one time range of the schedule index and of the
 * published index at a time. Dragging a scheduled Story to a new time reschedules it through the same operation as the drawer and offers Undo.
 */
export function NewsroomSchedulePage() {
  const session = useOptionalNewsDeskClient();
  const allowed = canReadNewsroomBoard(session?.shell.phase);
  const router = useRouter();
  const phone = usePhone();
  const { zone, error: zoneError } = useScheduleZone();
  const [range, setRange] = useState<{ from: string; to: string; view: ScheduleView } | null>(null);
  const [rows, setRows] = useState<ReturnType<typeof scheduleRows> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const request = useRef(0);
  const shown = useRef<ReturnType<typeof scheduleRows> | null>(null);
  shown.current = rows;

  useEffect(() => {
    if (!allowed || !zone || !range) return;
    const mine = ++request.current;
    setError(null);
    setNotice(null);
    Promise.all([loadNewsroomScheduledStories(range.from, range.to), loadNewsroomPublishedStories(range.from, range.to)]).then(([versions, published]) => {
      if (request.current === mine) setRows(scheduleRows(versions, published, zone));
    }, reason => {
      if (request.current === mine) setError(reason instanceof Error ? reason.message : "The schedule could not be loaded.");
    });
  }, [allowed, zone, range]);

  const onRange = useCallback((next: { from: string; to: string; view: ScheduleView }) => setRange(previous => previous && previous.from === next.from && previous.to === next.to && previous.view === next.view ? previous : next), []);
  /** Moves one scheduled Story to a UTC instant and shows the result in the calendar and the list; a refusal changes nothing. */
  const move = useCallback(async (id: string, at: string): Promise<{ ok: true; from: string } | { ok: false; message: string }> => {
    const item = shown.current?.items.find(candidate => candidate.id === id);
    if (!item || !canDrag(item)) return { ok: false, message: "That Story cannot be moved here." };
    if (Date.parse(at) <= Date.now()) return { ok: false, message: PAST_DROP_MESSAGE };
    try {
      await resolveArticlesBackend(isLocalPreviewEnabled()).actions.scheduleStory({ itemId: id, lineageId: item.lineageId, scheduledPublishAt: at });
    } catch (reason) {
      return { ok: false, message: reason instanceof Error ? reason.message : "The schedule could not be saved." };
    }
    setRows(previous => previous && zone ? { items: moveItem(previous.items, id, at, zone) } : previous);
    return { ok: true, from: item.at };
  }, [zone]);

  const reschedule = useCallback(async (id: string, at: string): Promise<RescheduleOutcome> => {
    const item = shown.current?.items.find(candidate => candidate.id === id);
    const outcome = await move(id, at);
    if (!zone || !item) return { ok: false, message: "That Story cannot be moved here." };
    if (!outcome.ok) {
      setNotice({ tone: "problem", text: `${outcome.message} “${item.title}” stays at ${formatScheduleTime(item.at, zone)}.` });
      return outcome;
    }
    setNotice({
      tone: "done", text: `Rescheduled “${item.title}” for ${formatScheduleTime(at, zone)}.`,
      undo: () => { void move(id, outcome.from).then(back => setNotice(back.ok
        ? { tone: "done", text: `“${item.title}” is back at ${formatScheduleTime(outcome.from, zone)}.` }
        : { tone: "problem", text: `${back.message} “${item.title}” stays at ${formatScheduleTime(at, zone)}.` })); },
    });
    return { ok: true };
  }, [move, zone]);

  const storyHref = (itemId: string) => getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(itemId)}`);

  if (!allowed) return <NewsDeskAccessGate shell={session?.shell ?? null} />;
  return <NewsroomOpsShell activeTab="schedule" appTitle={SITE_BRAND.appTitle} backLabel={SITE_BRAND.backToHomeLabel} pageTitle="Schedule">
    <div className="schedule-page" data-schedule-page>
      {zoneError ? <p className="schedule-problem" role="alert">{zoneError}</p>
        : zone === undefined ? <p className="schedule-zone-note" role="status">Loading the schedule…</p>
        : zone === null ? <p className="schedule-problem" role="status">Scheduling is off for this publication: its backend has no time zone set.</p>
        : <>
          <p className="schedule-zone-note" data-schedule-zone>All times are {zoneCity(zone)} time.</p>
          {error ? <NewsroomOpsStatusBanner tone="error">{error}</NewsroomOpsStatusBanner> : null}
          {phone === null ? null : <ScheduleCalendar items={rows?.items ?? []} zone={zone} phone={phone} onRange={onRange} onOpen={id => { const row = rows?.items.find(item => item.id === id); if (row) router.push(storyHref(id)); }} onReschedule={reschedule} />}
          {notice ? <p className="schedule-notice" data-schedule-notice data-schedule-notice-tone={notice.tone} role={notice.tone === "problem" ? "alert" : "status"}>
            {notice.tone === "problem" ? <TriangleAlert aria-hidden size={14} /> : <CalendarClock aria-hidden size={14} />}
            <span>{notice.text}</span>
            {notice.undo ? <button type="button" data-schedule-undo onClick={notice.undo}><Undo2 aria-hidden size={14} />Undo</button> : null}
          </p> : null}
          {rows && rows.items.every(item => item.kind === "published") && range ? <p className="schedule-empty" data-schedule-empty role="status">
            {EMPTY_TEXT[range.view]}
            <Link href={newsroomHref(contentItemBoardPathSegment())}><CalendarClock aria-hidden size={14} />Schedule a Story</Link>
          </p> : null}
          {rows && rows.items.length > 0 ? <section className="schedule-list-section" aria-labelledby="schedule-list-heading" data-schedule-list>
            <h2 id="schedule-list-heading">Everything in this view, as a list</h2>
            <ol className="schedule-list">
              {rows.items.map(item => {
                const Icon = SCHEDULE_ITEM_ICONS[item.kind];
                return <li className="schedule-list-item" key={item.id} data-schedule-item={item.id} data-schedule-kind={item.kind}>
                  <Link href={storyHref(item.id)}>{item.title}</Link>
                  <small><Icon aria-hidden size={12} /><span>{item.state}: {formatScheduleTime(item.at, zone, true)}{item.section ? ` · ${item.section}` : ""}</span></small>
                </li>;
              })}
            </ol>
          </section> : null}
        </>}
    </div>
  </NewsroomOpsShell>;
}

const sectionTitle = (section: string | null | undefined) => section ? displayNewsroomSectionShortTitle({ id: section } as NewsroomSectionRecord) : null;

/** Scheduled, overdue and superseded Stories from the schedule index, with the Stories published in the same range, earliest first. */
function scheduleRows(versions: readonly ContentItemVersionRecord[], published: readonly PublishedStoryRow[], zone: string): { items: ScheduleCalendarItem[] } {
  const now = new Date();
  const items: ScheduleCalendarItem[] = [];
  for (const version of versions) {
    const schedule = scheduleFromFields(version);
    if (!schedule) continue;
    const wording = scheduleWording(schedule, zone, now);
    items.push({
      id: version.id, lineageId: version.lineageId ?? version.id,
      title: version.headline || version.title || version.slug,
      section: sectionTitle(version.section),
      at: schedule.at, kind: wording.kind, state: STATE_WORD[wording.kind], label: wording.label,
    });
  }
  for (const story of published) {
    items.push({
      id: story.id, lineageId: story.lineageId, title: story.title, section: sectionTitle(story.section),
      at: story.publishedAt, kind: "published", state: "Published", label: `Published ${formatScheduleTime(story.publishedAt, zone)}`,
    });
  }
  return { items: items.sort((left, right) => left.at.localeCompare(right.at) || left.id.localeCompare(right.id)) };
}

/** The same items with one scheduled Story at its new time, worded again for it. */
function moveItem(items: readonly ScheduleCalendarItem[], id: string, at: string, zone: string): ScheduleCalendarItem[] {
  const wording = scheduleWording({ at, state: "scheduled", by: null, scheduledAt: null }, zone, new Date());
  return items.map(item => item.id !== id ? item : { ...item, at, kind: wording.kind, state: STATE_WORD[wording.kind], label: wording.label })
    .sort((left, right) => left.at.localeCompare(right.at) || left.id.localeCompare(right.id));
}
