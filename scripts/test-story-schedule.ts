import assert from "node:assert/strict";
import test from "node:test";
import { ORGANIZER_NAV_GROUPS } from "../lib/newsroom-organizer-nav";
import { publicationTimeZone } from "../lib/site-publication";
import { ownZoneTime, resolveWallTime, scheduleFromFields, scheduleKind, scheduleSentence, scheduleWording, wallTimeOf } from "../lib/story-schedule";
import { readScheduledRange, SCHEDULE_PAGE_STATES, type ScheduleQueryFetch } from "../lib/story-schedule-query";
import { projectionTypesSlice } from "../packages/papyrus/src/with-papyrus.mjs";

const NY = "America/New_York";
const NOW = new Date("2026-11-12T15:00:00Z");

test("a schedule reads from the row's fields, and a row that was never scheduled or was cleared has none", () => {
  assert.deepEqual(scheduleFromFields({ scheduledPublishAt: "2026-11-13T14:00:00.000Z", scheduleState: "scheduled", scheduledBy: "Sam", scheduledAt: "2026-11-12T01:00:00.000Z" }),
    { at: "2026-11-13T14:00:00.000Z", state: "scheduled", by: "Sam", scheduledAt: "2026-11-12T01:00:00.000Z" });
  assert.equal(scheduleFromFields({}), undefined);
  assert.equal(scheduleFromFields({ scheduledPublishAt: "2026-11-13T14:00:00.000Z", scheduleState: "cleared" }), undefined);
  assert.throws(() => scheduleFromFields({ scheduledPublishAt: "2026-11-13T14:00:00.000Z", scheduleState: "paused" }), /Unknown schedule state/);
});

test("each state has its words, in the publication's zone", () => {
  const at = "2026-11-16T09:00:00.000Z";   // 4:00 AM ET
  assert.equal(scheduleWording({ at, state: "scheduled", by: null, scheduledAt: null }, NY, NOW).text, "Scheduled: Mon 16 Nov, 4:00 AM ET");
  assert.equal(scheduleWording({ at: "2026-11-11T14:00:00.000Z", state: "scheduled", by: null, scheduledAt: null }, NY, NOW).text, "Overdue", "a time that passed while still scheduled is overdue");
  assert.equal(scheduleKind({ at, state: "overdue", by: null, scheduledAt: null }, NOW), "overdue");
  assert.equal(scheduleWording({ at, state: "superseded", by: null, scheduledAt: null }, NY, NOW).text, "Superseded: a newer version was saved");
  assert.match(scheduleWording({ at, state: "published", by: null, scheduledAt: null }, NY, NOW).text, /^Published as scheduled: Mon 16 Nov, 4:00 AM ET$/);
  assert.equal(scheduleSentence({ at, state: "scheduled", by: "Sam", scheduledAt: null }, NY), "Mon 16 Nov 2026, 4:00 AM ET (New York), by Sam");
});

test("the editor's own zone is a second line only when it differs", () => {
  assert.equal(ownZoneTime("2026-11-13T14:00:00.000Z", NY, NY), null);
  assert.equal(ownZoneTime("2026-11-13T14:00:00.000Z", NY, "Europe/London"), "2:00 PM GMT your time");
});

test("a wall-clock time becomes one UTC instant, none (the spring-forward gap) or two (the fall-back hour)", () => {
  assert.deepEqual(resolveWallTime("2026-11-13", "09:00", NY), { kind: "ok", utc: "2026-11-13T14:00:00.000Z" });
  assert.deepEqual(resolveWallTime("2026-07-01", "09:00", NY), { kind: "ok", utc: "2026-07-01T13:00:00.000Z" }, "daylight time is one hour less behind UTC");
  assert.deepEqual(resolveWallTime("2026-03-08", "02:30", NY), { kind: "gap", message: "That time does not exist on 8 March in New York. Pick another time." });
  assert.deepEqual(resolveWallTime("2026-03-08", "03:00", NY), { kind: "ok", utc: "2026-03-08T07:00:00.000Z" });
  assert.deepEqual(resolveWallTime("2026-11-01", "01:30", NY), { kind: "ambiguous", options: [{ utc: "2026-11-01T05:30:00.000Z", label: "01:30 EDT" }, { utc: "2026-11-01T06:30:00.000Z", label: "01:30 EST" }] });
  assert.deepEqual(resolveWallTime("2026-11-01", "02:30", NY), { kind: "ok", utc: "2026-11-01T07:30:00.000Z" });
  assert.deepEqual(resolveWallTime("2026-11-13", "09:00", "UTC"), { kind: "ok", utc: "2026-11-13T09:00:00.000Z" });
  assert.deepEqual(wallTimeOf("2026-11-13T14:00:00.000Z", NY), { date: "2026-11-13", time: "09:00" });
  assert.throws(() => resolveWallTime("", "09:00", NY), /Pick a date and a time/);
});

test("the publication's time zone is read from the site's projection slice, and a bad name is an error", () => {
  const env = (publication: unknown) => ({ NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES: JSON.stringify({ publication }) });
  assert.equal(publicationTimeZone(env({ timeZone: NY })), NY);
  assert.equal(publicationTimeZone(env({})), null, "a site that sets none has no scheduling");
  assert.equal(publicationTimeZone({}), null);
  assert.throws(() => publicationTimeZone(env({ timeZone: "Mars/Olympus" })), /not a time zone name/);
  assert.throws(() => publicationTimeZone(env({ timeZone: 5 })), /time zone name such as/);
  assert.deepEqual(projectionTypesSlice({ publication: { timeZone: NY, other: 1 } }).publication, { timeZone: NY }, "withPapyrus copies only the zone");
});

test("the Schedule destination is in the newsroom navigation only for a publication with a time zone", () => {
  const keys = ORGANIZER_NAV_GROUPS.flatMap((group) => group.items.map((item) => item.key));
  assert.equal(keys.includes("schedule"), Boolean(publicationTimeZone()));
});

test("the page reads one query per state on the schedule index, limited to the range, and follows every page", async () => {
  const seen: Record<string, unknown>[] = [];
  const row = (id: string, scheduledPublishAt: string, scheduleState: string) => ({ id, lineageId: id, versionNumber: 1, type: "article", status: "draft", slug: id, scheduledPublishAt, scheduleState });
  const fetch: ScheduleQueryFetch = async ({ field, variables, query }) => {
    seen.push(variables);
    assert.equal(field, "listItemsByScheduleStateAndScheduledPublishAt");
    assert.match(query, /scheduleState: \$scheduleState, scheduledPublishAt: \$scheduledPublishAt/);
    assert.deepEqual(variables.scheduledPublishAt, { between: ["2026-11-08T05:00:00.000Z", "2026-11-15T05:00:00.000Z"] });
    if (variables.scheduleState === "scheduled" && !variables.nextToken) return { items: [row("b", "2026-11-13T14:00:00.000Z", "scheduled")], nextToken: "more" };
    if (variables.scheduleState === "scheduled") return { items: [row("a", "2026-11-12T14:00:00.000Z", "scheduled")], nextToken: null };
    if (variables.scheduleState === "superseded") return { items: [row("c", "2026-11-14T14:00:00.000Z", "superseded")], nextToken: null };
    return { items: [], nextToken: null };
  };
  const rows = await readScheduledRange(fetch, "2026-11-08T05:00:00.000Z", "2026-11-15T05:00:00.000Z");
  assert.deepEqual(rows.map((entry) => entry.id), ["a", "b", "c"], "earliest first across states and pages");
  assert.deepEqual([...new Set(seen.map((variables) => variables.scheduleState))].sort(), [...SCHEDULE_PAGE_STATES].sort(), "one query per state");
  assert.equal(seen.length, SCHEDULE_PAGE_STATES.length + 1, "and the second page of one state");
});
