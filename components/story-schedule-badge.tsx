"use client";
import "./story-schedule.css";

import { CalendarClock, CircleCheck, CircleSlash, TriangleAlert, type LucideIcon } from "lucide-react";
import { scheduleWording, type ScheduleKind, type StorySchedule } from "../lib/story-schedule";

export const SCHEDULE_ICONS: Record<ScheduleKind, LucideIcon> = {
  scheduled: CalendarClock,
  overdue: TriangleAlert,
  superseded: CircleSlash,
  published: CircleCheck,
};

/** A schedule's state as an icon and words, in the publication's zone. Colour only repeats what the words say. */
export function StoryScheduleBadge({ schedule, zone, now = new Date() }: { schedule: StorySchedule; zone: string; now?: Date }) {
  const wording = scheduleWording(schedule, zone, now);
  const Icon = SCHEDULE_ICONS[wording.kind];
  return <span className="story-schedule-badge" data-schedule-kind={wording.kind} title={wording.label}>
    <Icon aria-hidden size={13} /><span>{wording.text}</span>
  </span>;
}
