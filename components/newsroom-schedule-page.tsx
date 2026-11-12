"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CalendarClock } from "lucide-react";
import "./newsroom-theme";
import { canReadNewsroomBoard, contentItemBoardPathSegment } from "../lib/newsroom-board";
import { displayNewsroomSectionShortTitle } from "../lib/newsroom-sections";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { newsroomHref } from "../lib/newsroom-base-path";
import { SITE_BRAND } from "../lib/site-brand";
import { publicationTimeZone } from "../lib/site-publication";
import { formatScheduleTime, scheduleFromFields, scheduleWording, zoneCity } from "../lib/story-schedule";
import type { ContentItemVersionRecord } from "../lib/content-item-lifecycle";
import type { NewsroomSectionRecord } from "../lib/category-repository";
import { loadNewsroomScheduledStories } from "./news-desk-taxonomy-client";
import { NewsDeskAccessGate } from "./newsroom-access-gate";
import { useOptionalNewsDeskClient } from "./news-desk-client-provider";
import { NewsroomOpsShell, NewsroomOpsStatusBanner } from "./newsroom-ops-shell";
import { SCHEDULE_ICONS } from "./story-schedule-badge";
import type { ScheduleCalendarItem, ScheduleView } from "./schedule-calendar";

/** FullCalendar is about 80 kB; it loads here and nowhere else. */
const ScheduleCalendar = dynamic(() => import("./schedule-calendar"), {
  ssr: false,
  loading: () => <p className="schedule-zone-note" role="status">Loading the calendar…</p>,
});

const STATE_WORD = { scheduled: "Scheduled", overdue: "Overdue", superseded: "Superseded" } as const;
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
 * The Schedule page: the Stories that are scheduled, overdue or superseded, by day, week or month in the publication's time zone, with a
 * plain list of the same items under the calendar for keyboard and screen-reader use. It reads one time range of the schedule index at a time.
 */
export function NewsroomSchedulePage() {
  const session = useOptionalNewsDeskClient();
  const allowed = canReadNewsroomBoard(session?.shell.phase);
  const router = useRouter();
  const phone = usePhone();
  const zoneResult = useMemo(() => { try { return { zone: publicationTimeZone(), error: null }; } catch (reason) { return { zone: null, error: reason instanceof Error ? reason.message : String(reason) }; } }, []);
  const zone = zoneResult.zone;
  const [range, setRange] = useState<{ from: string; to: string; view: ScheduleView } | null>(null);
  const [rows, setRows] = useState<ReturnType<typeof scheduleRows> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);

  useEffect(() => {
    if (!allowed || !zone || !range) return;
    const current = ++request.current;
    setError(null);
    loadNewsroomScheduledStories(range.from, range.to).then(versions => {
      if (request.current === current) setRows(scheduleRows(versions, zone));
    }, reason => {
      if (request.current === current) setError(reason instanceof Error ? reason.message : "The schedule could not be loaded.");
    });
  }, [allowed, zone, range]);

  const onRange = useCallback((next: { from: string; to: string; view: ScheduleView }) => setRange(previous => previous && previous.from === next.from && previous.to === next.to && previous.view === next.view ? previous : next), []);
  const storyHref = (itemId: string) => getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(itemId)}`);

  if (!allowed) return <NewsDeskAccessGate shell={session?.shell ?? null} />;
  return <NewsroomOpsShell activeTab="schedule" appTitle={SITE_BRAND.appTitle} backLabel={SITE_BRAND.backToHomeLabel} pageTitle="Schedule">
    <div className="schedule-page" data-schedule-page>
      {zoneResult.error ? <p className="schedule-problem" role="alert">{zoneResult.error}</p>
        : !zone ? <p className="schedule-problem" role="status">Scheduling is off: this publication has no time zone. Set publication.timeZone in the site&apos;s projection.json.</p>
        : <>
          <p className="schedule-zone-note" data-schedule-zone>All times are {zoneCity(zone)} time.</p>
          {error ? <NewsroomOpsStatusBanner tone="error">{error}</NewsroomOpsStatusBanner> : null}
          {phone === null ? null : <ScheduleCalendar items={rows?.items ?? []} zone={zone} phone={phone} onRange={onRange} onOpen={id => { const row = rows?.items.find(item => item.id === id); if (row) router.push(storyHref(id)); }} />}
          {rows && rows.items.length === 0 && range ? <p className="schedule-empty" data-schedule-empty role="status">
            {EMPTY_TEXT[range.view]}
            <Link href={newsroomHref(contentItemBoardPathSegment())}><CalendarClock aria-hidden size={14} />Schedule a Story</Link>
          </p> : null}
          {rows && rows.items.length > 0 ? <section className="schedule-list-section" aria-labelledby="schedule-list-heading" data-schedule-list>
            <h2 id="schedule-list-heading">Everything in this view, as a list</h2>
            <ol className="schedule-list">
              {rows.items.map(item => {
                const Icon = SCHEDULE_ICONS[item.kind];
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

function scheduleRows(versions: readonly ContentItemVersionRecord[], zone: string): { items: ScheduleCalendarItem[] } {
  const now = new Date();
  const items: ScheduleCalendarItem[] = [];
  for (const version of versions) {
    const schedule = scheduleFromFields(version);
    if (!schedule) continue;
    const wording = scheduleWording(schedule, zone, now);
    items.push({
      id: version.id,
      title: version.headline || version.title || version.slug,
      section: version.section ? displayNewsroomSectionShortTitle({ id: version.section } as NewsroomSectionRecord) : null,
      at: schedule.at, kind: wording.kind, state: STATE_WORD[wording.kind], label: wording.label,
    });
  }
  return { items };
}
