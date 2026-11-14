"use client";
import { useMemo, useState, useCallback } from "react";
import { Calendar, luxonLocalizer, Views, type View } from "react-big-calendar";
import withDragAndDrop from "react-big-calendar/lib/addons/dragAndDrop";
import { DateTime } from "luxon";
import "react-big-calendar/lib/css/react-big-calendar.css";
import "react-big-calendar/lib/addons/dragAndDrop/styles.css";
import "./rbc-overrides.css";
import { makeItems, ZONE, type Item, type Status } from "../lib/data";
import { StatusBadge } from "./StatusBadge";
import { ItemList } from "./ItemList";
import { useTheme } from "../lib/theme";

const localizer = luxonLocalizer(DateTime, { firstDayOfWeek: 1 });
const DnD = withDragAndDrop<any, object>(Calendar as any);
// RBC works in browser-local Dates; shift UTC to "wall clock in ZONE" and back.
const toWall = (utc: string) => { const z = DateTime.fromISO(utc).setZone(ZONE); return new Date(z.year, z.month - 1, z.day, z.hour, z.minute); };
const toUtc = (d: Date) => DateTime.fromObject({ year: d.getFullYear(), month: d.getMonth() + 1, day: d.getDate(), hour: d.getHours(), minute: d.getMinutes() }, { zone: ZONE }).toUTC().toISO()!;

export default function RBC() {
  useTheme();
  const [items, setItems] = useState<Item[]>(() => makeItems());
  const [view, setView] = useState<View>(Views.WEEK);
  const [date, setDate] = useState(() => toWall(DateTime.now().toUTC().toISO()!));
  const events = useMemo(() => items.map((i) => { const s = toWall(i.startUtc); return { id: i.id, title: i.title, status: i.status, start: s, end: new Date(s.getTime() + 30 * 60000) }; }), [items]);
  const onDrop = useCallback(({ event, start }: any) => {
    setItems((cur) => cur.map((i) => (i.id === event.id ? { ...i, startUtc: toUtc(new Date(start)) } : i)));
  }, []);
  return (
    <>
      <DnD
        localizer={localizer}
        events={events}
        view={view}
        onView={setView}
        date={date}
        onNavigate={setDate}
        views={[Views.DAY, Views.WEEK, Views.MONTH]}
        resizable={false}
        onEventDrop={onDrop}
        style={{ height: 720 }}
        components={{ event: ({ event }: any) => (<span className="ev"><StatusBadge status={event.status as Status} /> <span className="ev-t">{event.title}</span></span>) }}
      />
      <ItemList items={items} />
    </>
  );
}
