/**
 * A Story version's schedule, as the board, the drawer and the Schedule page show it (docs/plans/scheduled-publishing-and-announcements.md).
 *
 * The backend keeps one UTC instant on the version's Item row (`scheduledPublishAt`) with its state (`scheduleState`), who set it (`scheduledBy`) and
 * when (`scheduledAt`). Everything an editor reads or types is in the publication's named time zone; this module converts between the two and words each
 * state. Pure, so the rules are tested without a browser (scripts/test-story-schedule.ts).
 */

/** The stored `scheduleState` (docs/scheduled-publishing.md): present only while a schedule exists. Overdue is derived from the time, never stored. */
export const SCHEDULE_STATES = ["scheduled", "publishing", "blocked"] as const;
export type ScheduleState = (typeof SCHEDULE_STATES)[number];

/** The schedule fields of an Item row. All absent on a version that was never scheduled (the index on them is sparse). */
export type ScheduleFields = {
  scheduledPublishAt?: string | null;
  scheduledBy?: string | null;
  scheduledAt?: string | null;
  scheduleState?: string | null;
};

/** The GraphQL selection of the schedule fields, for every query that reads a Story row. */
export const SCHEDULE_ROW_FIELDS = "scheduledPublishAt scheduledBy scheduledAt scheduleState";

export type StorySchedule = {
  /** The UTC instant the version goes live. */
  at: string;
  state: ScheduleState;
  by: string | null;
  scheduledAt: string | null;
};

export function scheduleFromFields(fields: ScheduleFields): StorySchedule | undefined {
  const state = fields.scheduleState;
  if (!fields.scheduledPublishAt || !state) return undefined;
  if (!(SCHEDULE_STATES as readonly string[]).includes(state)) throw new Error(`Unknown schedule state "${state}".`);
  return { at: fields.scheduledPublishAt, state: state as ScheduleState, by: fields.scheduledBy ?? null, scheduledAt: fields.scheduledAt ?? null };
}

/**
 * The schedule the drawer shows for a Story, from its `schedule_list` answer: the newest scheduled version, since a schedule that sits on an earlier version
 * is the one a newer save superseded. The state is the stored one; Overdue is derived from the time (`scheduleKind`), as the backend derives it.
 */
export function scheduleFromEntries(entries: readonly { versionNumber: number | null; storedState: string; scheduledPublishAt: string; scheduledBy: string | null; scheduledAt: string | null }[]): StorySchedule | undefined {
  const newest = [...entries].sort((left, right) => (right.versionNumber ?? 0) - (left.versionNumber ?? 0))[0];
  return newest ? scheduleFromFields({ scheduledPublishAt: newest.scheduledPublishAt, scheduleState: newest.storedState, scheduledBy: newest.scheduledBy, scheduledAt: newest.scheduledAt }) : undefined;
}

/** The schedule a successful `schedule` call recorded: none after a clear, else scheduled for the instant that was sent. */
export function scheduleFromResult(result: { scheduledPublishAt: string | null; scheduledBy: string | null }, at: Date = new Date()): StorySchedule | undefined {
  return result.scheduledPublishAt ? { at: result.scheduledPublishAt, state: "scheduled", by: result.scheduledBy, scheduledAt: at.toISOString() } : undefined;
}

/**
 * What a reader sees. A time that has passed while the version is still scheduled or being published is Overdue (derived, as the backend derives it); a blocked
 * schedule is Superseded: a newer version was saved after it was scheduled.
 */
export type ScheduleKind = "scheduled" | "overdue" | "superseded";

export function scheduleKind(schedule: StorySchedule, now: Date): ScheduleKind {
  if (schedule.state === "blocked") return "superseded";
  return Date.parse(schedule.at) <= now.getTime() ? "overdue" : "scheduled";
}

const part = (parts: Intl.DateTimeFormatPart[], type: Intl.DateTimeFormatPartTypes) => parts.find(candidate => candidate.type === type)?.value ?? "";

/** `Mon 16 Nov, 4:00 AM ET`: the instant in the zone, with the year when `withYear`. */
export function formatScheduleTime(iso: string, zone: string, withYear = false): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone, weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "shortGeneric",
  }).formatToParts(new Date(iso));
  const date = `${part(parts, "weekday")} ${part(parts, "day")} ${part(parts, "month")}${withYear ? ` ${part(parts, "year")}` : ""}`;
  return `${date}, ${part(parts, "hour")}:${part(parts, "minute")} ${part(parts, "dayPeriod")} ${part(parts, "timeZoneName")}`;
}

/** `America/New_York` as "New York". */
export function zoneCity(zone: string): string {
  return (zone.split("/").pop() ?? zone).replace(/_/g, " ");
}

export type ScheduleWording = {
  kind: ScheduleKind;
  /** The short line for a card or a calendar event. */
  text: string;
  /** The same with every fact, for a tooltip and a screen reader. */
  label: string;
};

export function scheduleWording(schedule: StorySchedule, zone: string, now: Date): ScheduleWording {
  const kind = scheduleKind(schedule, now);
  const time = formatScheduleTime(schedule.at, zone);
  if (kind === "scheduled") return { kind, text: `Scheduled: ${time}`, label: `Scheduled to publish ${time}` };
  if (kind === "overdue") return { kind, text: "Overdue", label: `Overdue: it was scheduled to publish ${time} and has not been published` };
  return { kind, text: "Superseded: a newer version was saved", label: `Superseded: a newer version was saved after this was scheduled for ${time}. Schedule it again.` };
}

/** The drawer's line: `Scheduled for Thu 13 Nov 2026, 9:00 AM ET (New York), by Sam`. */
export function scheduleSentence(schedule: StorySchedule, zone: string): string {
  const by = schedule.by ? `, by ${schedule.by}` : "";
  return `${formatScheduleTime(schedule.at, zone, true)} (${zoneCity(zone)})${by}`;
}

/** The same instant in the browser's own zone, for the small line under the drawer's time; null when it is the publication's zone. */
export function ownZoneTime(iso: string, publicationZone: string, ownZone: string = Intl.DateTimeFormat().resolvedOptions().timeZone): string | null {
  if (ownZone === publicationZone) return null;
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: ownZone, hour: "numeric", minute: "2-digit", timeZoneName: "short" }).formatToParts(new Date(iso));
  return `${part(parts, "hour")}:${part(parts, "minute")} ${part(parts, "dayPeriod")} ${part(parts, "timeZoneName")} your time`;
}

function offsetMinutes(utcMs: number, zone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric",
  }).formatToParts(new Date(utcMs));
  const asUtc = Date.UTC(Number(part(parts, "year")), Number(part(parts, "month")) - 1, Number(part(parts, "day")), Number(part(parts, "hour")), Number(part(parts, "minute")), Number(part(parts, "second")));
  return Math.round((asUtc - Math.floor(utcMs / 1000) * 1000) / 60_000);
}

export type WallTime =
  | { kind: "ok"; utc: string }
  | { kind: "gap"; message: string }
  | { kind: "ambiguous"; options: { utc: string; label: string }[] };

/**
 * The instant for a wall-clock date and time (`2026-11-13`, `09:00`) in the zone. A time that does not exist (the spring-forward gap) is a plain refusal and a
 * time that happens twice (fall back) lists both instants for the editor to choose from. Every offset the zone has within a day of the wall time is tried; an
 * offset is right when the zone really is on it at the instant that gives.
 */
export function resolveWallTime(date: string, time: string, zone: string): WallTime {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  const clock = /^(\d{2}):(\d{2})$/.exec(time);
  if (!match || !clock) throw new Error("Pick a date and a time.");
  const wall = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(clock[1]), Number(clock[2]));
  const day = 24 * 60 * 60 * 1000;
  const offsets = new Set([offsetMinutes(wall - day, zone), offsetMinutes(wall + day, zone)]);
  const valid = [...offsets].map(offset => wall - offset * 60_000).filter(utc => offsetMinutes(utc, zone) === (wall - utc) / 60_000).sort((a, b) => a - b);
  if (valid.length === 0) {
    const label = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "numeric", month: "long" }).format(new Date(wall));
    return { kind: "gap", message: `That time does not exist on ${label} in ${zoneCity(zone)}. Pick another time.` };
  }
  if (valid.length === 1) return { kind: "ok", utc: new Date(valid[0]).toISOString() };
  const abbreviation = (utc: number) => part(new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "short" }).formatToParts(new Date(utc)), "timeZoneName");
  return { kind: "ambiguous", options: valid.map(utc => ({ utc: new Date(utc).toISOString(), label: `${time} ${abbreviation(utc)}` })) };
}

/** The wall-clock date (`2026-11-13`) and time (`09:00`) of an instant in the zone, to fill the pickers. */
export function wallTimeOf(iso: string, zone: string): { date: string; time: string } {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).formatToParts(new Date(iso));
  return { date: `${part(parts, "year")}-${part(parts, "month")}-${part(parts, "day")}`, time: `${part(parts, "hour")}:${part(parts, "minute")}` };
}

export const PAST_TIME_MESSAGE = "That time has passed. Pick a time in the future, or use Publish.";
