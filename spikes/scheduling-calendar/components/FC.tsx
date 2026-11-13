"use client";
import { useMemo, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import classicTheme from "@fullcalendar/react/themes/classic";
import dayGrid from "@fullcalendar/react/daygrid";
import timeGrid from "@fullcalendar/react/timegrid";
import interaction from "@fullcalendar/react/interaction";
import "@fullcalendar/react/skeleton.css";
import "@fullcalendar/react/themes/classic/theme.css";
import "@fullcalendar/react/themes/classic/palette.css";
import "./fc-overrides.css";
import { makeItems, ZONE, STATUS_LABEL, type Item, type Status } from "../lib/data";
import { StatusBadge } from "./StatusBadge";
import { ItemList } from "./ItemList";
import { useTheme } from "../lib/theme";

export default function FC() {
  useTheme();
  const [items, setItems] = useState<Item[]>(() => makeItems());
  const events = useMemo(() => items.map((i) => ({ id: i.id, title: i.title, start: i.startUtc, extendedProps: { status: i.status } })), [items]);
  return (
    <>
      <FullCalendar
        plugins={[classicTheme, dayGrid, timeGrid, interaction]}
        timeZone={ZONE}
        initialView="timeGridWeek"
        headerToolbar={{ left: "prev,next today", center: "title", right: "timeGridDay,timeGridWeek,dayGridMonth" }}
        events={events}
        editable
        eventDurationEditable={false}
        defaultTimedEventDuration="00:30"
        height="auto"
        eventContent={(arg: any) => (
          <span className="ev"><StatusBadge status={arg.event.extendedProps.status as Status} /> <span className="ev-t">{arg.event.title}</span></span>
        )}
        eventDrop={(info: any) => {
          const iso = new Date(info.event.start).toISOString();
          setItems((cur) => cur.map((i) => (i.id === info.event.id ? { ...i, startUtc: iso } : i)));
        }}
      />
      <ItemList items={items} />
    </>
  );
}
