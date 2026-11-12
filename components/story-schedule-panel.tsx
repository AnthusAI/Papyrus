"use client";

import { useEffect, useId, useState } from "react";
import { CalendarClock, CalendarX2, Pencil } from "lucide-react";
import {
  PAST_TIME_MESSAGE,
  ownZoneTime,
  resolveWallTime,
  scheduleSentence,
  scheduleKind,
  wallTimeOf,
  zoneCity,
  type StorySchedule,
  type WallTime,
} from "../lib/story-schedule";
import { StoryScheduleBadge } from "./story-schedule-badge";

function failureText(reason: unknown): string {
  return reason instanceof Error && reason.message ? reason.message : "The schedule could not be saved.";
}

/**
 * The Story drawer's schedule row, beside the Published state and the Publish button: when this version goes live (in the publication's zone, with the editor's
 * own zone in small type when it differs), and the controls to set, change or clear it. The change shows at once and goes back to what was saved if the backend
 * refuses it; what the editor typed stays in the form so nothing has to be typed again. A wall-clock time that does not exist (the spring-forward gap) is refused
 * here with a plain message; one that happens twice (fall back) asks which one. Publish now is the editor's own button and is not touched.
 */
export function StorySchedulePanel({ zone, schedule, blockedReason, save, onChanged }: {
  zone: string;
  /** What was last saved. */
  schedule: StorySchedule | undefined;
  /** Why scheduling is off right now, shown instead of the controls' hint (unsaved changes, no saved version yet). */
  blockedReason: string | null;
  /** Saves a UTC instant, or clears with null, and returns the schedule the backend recorded. */
  save: (scheduledPublishAt: string | null) => Promise<StorySchedule | undefined>;
  onChanged?: (schedule: StorySchedule | undefined) => void;
}) {
  const ids = useId();
  const [optimistic, setOptimistic] = useState<{ schedule: StorySchedule | undefined } | null>(null);
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("09:00");
  const [choices, setChoices] = useState<Extract<WallTime, { kind: "ambiguous" }>["options"] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const shown = optimistic ? optimistic.schedule : schedule;
  const now = new Date();
  const kind = shown ? scheduleKind(shown, now) : null;

  useEffect(() => { setOptimistic(null); }, [schedule]);

  const open = () => {
    const start = shown ? wallTimeOf(shown.at, zone) : wallTimeOf(new Date(Date.now() + 24 * 3_600_000).toISOString(), zone);
    setDate(start.date); setTime(shown ? start.time : "09:00"); setChoices(null); setChosen(null); setProblem(null); setEditing(true);
  };

  const apply = async (scheduledPublishAt: string | null) => {
    const previous = schedule;
    const next: StorySchedule | undefined = scheduledPublishAt === null ? undefined : { at: scheduledPublishAt, state: "scheduled", by: shown?.by ?? null, scheduledAt: new Date().toISOString() };
    setOptimistic({ schedule: next }); setEditing(false); setProblem(null); setSaving(true);
    try {
      const saved = await save(scheduledPublishAt);
      setOptimistic({ schedule: saved });
      onChanged?.(saved);
    } catch (reason) {
      setOptimistic({ schedule: previous });   // back to what was saved; the form below still holds what was typed
      setProblem(failureText(reason));
      if (scheduledPublishAt !== null) setEditing(true);
    } finally {
      setSaving(false);
    }
  };

  const submit = () => {
    setProblem(null);
    if (!date || !time) { setProblem("Pick a date and a time."); return; }
    let resolved: WallTime;
    try { resolved = resolveWallTime(date, time, zone); } catch (reason) { setProblem(failureText(reason)); return; }
    if (resolved.kind === "gap") { setProblem(resolved.message); setChoices(null); return; }
    if (resolved.kind === "ambiguous") {
      if (!chosen || !resolved.options.some(option => option.utc === chosen)) { setChoices(resolved.options); setChosen(null); setProblem("That time happens twice that night. Choose which one."); return; }
      if (Date.parse(chosen) <= Date.now()) { setProblem(PAST_TIME_MESSAGE); return; }
      void apply(chosen);
      return;
    }
    if (Date.parse(resolved.utc) <= Date.now()) { setProblem(PAST_TIME_MESSAGE); return; }
    void apply(resolved.utc);
  };

  const own = shown ? ownZoneTime(shown.at, zone) : null;
  const controlsOff = blockedReason !== null || saving;

  return <section className="story-schedule" data-story-schedule-panel aria-labelledby={`${ids}-heading`}>
    <h3 className="story-schedule-heading" id={`${ids}-heading`}><CalendarClock aria-hidden size={15} />Schedule</h3>
    {shown ? <div className="story-schedule-current" data-story-schedule-current={kind ?? undefined}>
      <StoryScheduleBadge schedule={shown} zone={zone} now={now} />
      <p className="story-schedule-sentence" data-story-schedule-sentence>
        {kind === "published" ? "Published as scheduled" : kind === "overdue" ? "Was scheduled for" : kind === "superseded" ? "Was scheduled for" : "Scheduled for"} {scheduleSentence(shown, zone)}
      </p>
      {own ? <p className="story-schedule-own" data-story-schedule-own>{own}</p> : null}
      {kind === "superseded" ? <p className="story-schedule-note">A newer version was saved after this was scheduled. Schedule it again.</p> : null}
      {kind === "overdue" ? <p className="story-schedule-note">It was not published at its time. Publish it now, or pick a new time.</p> : null}
    </div> : <p className="story-schedule-note" data-story-schedule-none>Not scheduled. Use Publish to publish now, or pick a time. Times are in {zoneCity(zone)} time.</p>}
    {problem && !editing ? <p className="story-schedule-problem" role="alert" data-story-schedule-problem>{problem}</p> : null}
    {editing ? <form className="story-schedule-form" data-story-schedule-form onSubmit={event => { event.preventDefault(); submit(); }}>
      <div className="story-schedule-fields">
        <label htmlFor={`${ids}-date`}>Date</label>
        <input id={`${ids}-date`} type="date" value={date} onChange={event => { setDate(event.target.value); setChoices(null); setChosen(null); }} data-story-schedule-date />
        <label htmlFor={`${ids}-time`}>Time ({zoneCity(zone)})</label>
        <input id={`${ids}-time`} type="time" value={time} onChange={event => { setTime(event.target.value); setChoices(null); setChosen(null); }} data-story-schedule-time />
      </div>
      {choices ? <fieldset className="story-schedule-choices" data-story-schedule-choices>
        <legend>Which one?</legend>
        {choices.map(option => <label key={option.utc}>
          <input type="radio" name={`${ids}-which`} value={option.utc} checked={chosen === option.utc} onChange={() => { setChosen(option.utc); setProblem(null); }} />
          {option.label}
        </label>)}
      </fieldset> : null}
      {problem ? <p className="story-schedule-problem" role="alert" data-story-schedule-problem>{problem}</p> : null}
      <div className="story-schedule-buttons">
        <button type="submit" className="story-schedule-button" disabled={saving} data-story-schedule-save><CalendarClock aria-hidden size={14} />Save schedule</button>
        <button type="button" className="story-schedule-button" onClick={() => { setEditing(false); setProblem(null); }} data-story-schedule-cancel>Cancel</button>
      </div>
    </form> : <div className="story-schedule-buttons">
      <button type="button" className="story-schedule-button" disabled={controlsOff} onClick={open} data-story-schedule-open>
        {shown ? <Pencil aria-hidden size={14} /> : <CalendarClock aria-hidden size={14} />}{shown && kind !== "published" ? "Change time" : "Schedule…"}
      </button>
      {shown && kind !== "published" ? <button type="button" className="story-schedule-button" disabled={controlsOff} onClick={() => void apply(null)} data-story-schedule-clear>
        <CalendarX2 aria-hidden size={14} />Unschedule
      </button> : null}
    </div>}
    {blockedReason ? <p className="story-schedule-note" data-story-schedule-hint>{blockedReason}</p> : null}
  </section>;
}
