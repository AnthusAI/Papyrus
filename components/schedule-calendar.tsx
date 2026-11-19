"use client";

import FullCalendar from "@fullcalendar/react";
import classicTheme from "@fullcalendar/react/themes/classic";
import dayGrid from "@fullcalendar/react/daygrid";
import timeGrid from "@fullcalendar/react/timegrid";
import list from "@fullcalendar/react/list";
import interaction from "@fullcalendar/react/interaction";
import "@fullcalendar/react/skeleton.css";
import "@fullcalendar/react/themes/classic/theme.css";
import "./schedule-calendar.css";
import { CircleCheck, type LucideIcon } from "lucide-react";
import { SCHEDULE_ICONS } from "./story-schedule-badge";
import type { ScheduleKind } from "../lib/story-schedule";

/** What an item on the page is: a schedule state, or a Story that already went out. */
export type ScheduleItemKind = ScheduleKind | "published";
export const SCHEDULE_ITEM_ICONS: Record<ScheduleItemKind, LucideIcon> = { ...SCHEDULE_ICONS, published: CircleCheck };

export type ScheduleCalendarItem = {
  id: string;
  title: string;
  section: string | null;
  lineageId: string;
  /** The UTC instant: when it goes live, or when it went live. */
  at: string;
  kind: ScheduleItemKind;
  /** The state in one or two words: Scheduled, Overdue, Superseded, Published. */
  state: string;
  /** Every fact, for a screen reader. */
  label: string;
};

export type ScheduleView = "day" | "week" | "month";
export type RescheduleOutcome = { ok: true } | { ok: false; message: string };
/** Only a Story that is still waiting for its time moves by dragging; an overdue, superseded or published one is changed in its drawer or not at all. */
export const canDrag = (item: Pick<ScheduleCalendarItem, "kind">): boolean => item.kind === "scheduled";
const VIEWS = {
  wide: { initial: "timeGridWeek", right: "timeGridDay,timeGridWeek,dayGridMonth", of: { timeGridDay: "day", timeGridWeek: "week", dayGridMonth: "month" } },
  phone: { initial: "listWeek", right: "listDay,listWeek,listMonth", of: { listDay: "day", listWeek: "week", listMonth: "month" } },
} as const;

const clockTime = (iso: string, zone: string) => new Intl.DateTimeFormat("en-US", { timeZone: zone, hour: "numeric", minute: "2-digit" }).format(new Date(iso));

/**
 * FullCalendar 7 in the publication's named time zone, loaded only on the Schedule page. Week is the default; Day and Month switch; a phone gets the lists of
 * the same three spans because the seven-day grid does not fit 375 pixels. Events are focusable (`eventInteractive`) and open the Story. The page owns the data:
 * the calendar reports the range on screen and shows the items it is given. A scheduled Story can be dragged in the week, day and month grids: the drop asks the
 * page to reschedule it (which revalidates the time with the backend) and the calendar puts it back when the page says no.
 */
export default function ScheduleCalendar({ items, zone, phone, onRange, onOpen, onReschedule }: {
  items: readonly ScheduleCalendarItem[];
  zone: string;
  phone: boolean;
  onRange: (range: { from: string; to: string; view: ScheduleView }) => void;
  onOpen: (id: string) => void;
  /** Asks to move a Story to a UTC instant; the calendar reverts the drop on a refusal. */
  onReschedule: (id: string, at: string) => Promise<RescheduleOutcome>;
}) {
  const views = phone ? VIEWS.phone : VIEWS.wide;
  return <div className="schedule-calendar" data-schedule-calendar data-schedule-layout={phone ? "list" : "grid"}>
    <FullCalendar
      key={phone ? "phone" : "wide"}
      plugins={[classicTheme, dayGrid, timeGrid, list, interaction]}
      timeZone={zone}
      initialView={views.initial}
      headerToolbar={{ left: "prev,next today", center: "title", right: views.right }}
      buttons={{ today: { text: "Today" }, ...Object.fromEntries(Object.entries(views.of).map(([view, span]) => [view, { text: span[0].toUpperCase() + span.slice(1) }])) }}
      events={items.map(item => ({ id: item.id, title: item.title, start: item.at, startEditable: canDrag(item), extendedProps: item }))}
      eventInteractive
      eventDurationEditable={false}
      eventDrop={arg => { void onReschedule(arg.event.id, new Date(arg.event.startStr).toISOString()).then(outcome => { if (!outcome.ok) arg.revert(); }); }}
      eventDisplay="block"
      defaultTimedEventDuration="02:00"
      height="auto"
      datesSet={arg => onRange({ from: new Date(arg.startStr).toISOString(), to: new Date(arg.endStr).toISOString(), view: (views.of as Record<string, ScheduleView>)[arg.view.type] ?? "week" })}
      eventClick={arg => { arg.jsEvent.preventDefault(); onOpen(arg.event.id); }}
      eventContent={arg => {
        const item = arg.event.extendedProps as ScheduleCalendarItem;
        const Icon = SCHEDULE_ITEM_ICONS[item.kind];
        return <span className="schedule-event" data-schedule-kind={item.kind} title={item.label}>
          <Icon aria-hidden size={13} />
          <span className="schedule-event-text">
            <span className="schedule-event-state">{phone ? "" : `${clockTime(item.at, zone)} `}{item.state}</span>
            <span className="schedule-event-title">{item.title}</span>
            {item.section ? <span className="schedule-event-section">{item.section}</span> : null}
          </span>
        </span>;
      }}
    />
  </div>;
}
