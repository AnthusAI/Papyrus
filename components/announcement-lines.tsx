"use client";
import "./announcement-lines.css";

import { useCallback, useEffect, useRef, useState } from "react";
import { Megaphone, TriangleAlert } from "lucide-react";
import { channelName, kindName, readDoor, waitingWords, type AnnouncementEntry, type AnnouncementsDoor, type AnnouncementsRecent, type DeliveryLine } from "../lib/announcement-lines";
import { formatWhen } from "../lib/announcements-model";
import { MarkIcon } from "./announcement-marks";

const OUTCOME_MARK = { started: "circle-help", unknown: "circle-help", sent: "circle-check", refused: "circle-x" } as const;

/**
 * One Delivery as one line: the channel and account, its state, how it is reviewed, what it waits for, its last attempt, and what needs a person's eye. Every state is a mark and
 * words together (a flat fill only repeats them), so the line reads without colour. The words and marks are the backend's (`lines.py`).
 */
export function DeliveryLineView({ line }: { line: DeliveryLine }) {
  const waiting = waitingWords(line, formatWhen);
  return (
    <li className="ann-line" data-delivery-line={`${line.channel}#${line.accountId}`} data-delivery-state={line.state}>
      <p className="ann-line__head">
        <strong data-delivery-channel>{channelName(line.channel)} <span className="ann-line__account">{line.accountId}</span></strong>
        <span className="ann-line__state" data-delivery-state-words><MarkIcon mark={line.mark} /> {line.words}</span>
        {line.attention.map((item) => (
          <span className="ann-line__attention" data-attention={item.kind} key={item.kind}><MarkIcon mark={item.mark} /> {item.words}</span>
        ))}
      </p>
      {line.approval ? <p className="ann-line__review" data-delivery-review><MarkIcon mark={line.approval.mark} /> {line.approval.words}</p> : null}
      {waiting ? <p className="ann-line__quiet" data-delivery-waiting>{waiting}</p> : null}
      {line.lastAttempt ? (
        <p className="ann-line__quiet" data-delivery-attempt={line.lastAttempt.outcome}>
          <MarkIcon mark={OUTCOME_MARK[line.lastAttempt.outcome]} /> Attempt {line.lastAttempt.number}: {line.lastAttempt.words}{line.lastAttempt.code ? ` (${line.lastAttempt.code})` : ""}
          {line.lastAttempt.at ? `, ${formatWhen(line.lastAttempt.at)}` : ""}
          {line.resultUrl ? <> &middot; <a href={line.resultUrl} target="_blank" rel="noreferrer">view</a></> : null}
        </p>
      ) : null}
    </li>
  );
}

/** One Announcement: what decided it, when it goes, its one open review flag, and one line for each of its Deliveries. */
export function AnnouncementView({ entry, showStories = false }: { entry: AnnouncementEntry; showStories?: boolean }) {
  return (
    <section className="ann-entry" data-announcement-entry={entry.id} data-announcement-kind={entry.kind}>
      <header className="ann-entry__head">
        <strong>{kindName(entry.kind)}</strong>
        <span className="ann-line__quiet">{formatWhen(entry.releaseAt)}{entry.versionLookedAt ? `, version ${entry.versionLookedAt} of the Story` : ""}</span>
      </header>
      {showStories && entry.stories?.length ? (
        <p className="ann-entry__stories" data-announcement-stories>{entry.stories.map((story) => story.title).join(" · ")}</p>
      ) : null}
      {entry.reviewFlag ? (
        <p className="ann-flag" data-review-flag>
          <MarkIcon mark={entry.reviewFlag.mark} size={16} />
          <span><strong>{entry.reviewFlag.words}</strong>{entry.reviewFlag.ask ? <> {entry.reviewFlag.ask}</> : null}</span>
        </p>
      ) : null}
      <ul className="ann-lines" data-delivery-lines>
        {entry.deliveries.map((line) => <DeliveryLineView key={line.id} line={line} />)}
      </ul>
    </section>
  );
}

function Problem({ text }: { text: string }) {
  return <p className="ann-line__quiet ann-problem" data-announcements-problem><TriangleAlert aria-hidden="true" size={14} /> {text}</p>;
}

type Read<T> = { status: "loading" } | { status: "problem"; text: string } | { status: "ready"; value: T };

/**
 * The Story drawer's "where it was announced": one line for each Delivery, under the Announcement that decided it, read through the Story's `announces` relation (one indexed
 * read, never a table listing). It reads when the Story opens and never subscribes to anything.
 */
export function StoryAnnouncementsCard({ lineageId, door }: { lineageId: string; door: AnnouncementsDoor }) {
  const [read, setRead] = useState<Read<AnnouncementEntry[]>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setRead({ status: "loading" });
    readDoor(door, "announcements_where", { story: lineageId })
      .then((answer) => { if (!cancelled) setRead({ status: "ready", value: answer.announcements }); })
      .catch((error: unknown) => { if (!cancelled) setRead({ status: "problem", text: `Where this Story was announced could not be read. ${error instanceof Error ? error.message : ""}`.trim() }); });
    return () => { cancelled = true; };
  }, [door, lineageId]);

  return (
    <section className="ann-card" data-story-announcements aria-labelledby={`ann-story-${lineageId}`}>
      <h3 className="ann-card__heading" id={`ann-story-${lineageId}`}><Megaphone aria-hidden="true" size={15} />Where it was announced</h3>
      {read.status === "loading" ? <p className="ann-line__quiet" data-story-announcements-loading>Reading…</p> : null}
      {read.status === "problem" ? <Problem text={read.text} /> : null}
      {read.status === "ready" && read.value.length === 0 ? <p className="ann-line__quiet" data-story-announcements-none>This Story has not been announced.</p> : null}
      {read.status === "ready" ? read.value.map((entry) => <AnnouncementView entry={entry} key={entry.id} />) : null}
    </section>
  );
}

/**
 * The Announcements list: what is overdue first, then the Announcements newest first, one line for each Delivery. A page ends where the release time changes; "Show older" asks for the
 * page after it. It reads on open and when asked, and never subscribes to anything.
 */
export function AnnouncementsList({ door }: { door: AnnouncementsDoor }) {
  const [first, setFirst] = useState<Read<AnnouncementsRecent>>({ status: "loading" });
  const [older, setOlder] = useState<AnnouncementEntry[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderProblem, setOlderProblem] = useState<string | null>(null);
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);

  const load = useCallback(async () => {
    try {
      const answer = await readDoor(door, "announcements_recent", {});
      if (!live.current) return;
      setFirst({ status: "ready", value: answer });
      setOlder([]);
      setNext(answer.next);
    } catch (error) {
      if (live.current) setFirst({ status: "problem", text: `The list could not be read. ${error instanceof Error ? error.message : ""}`.trim() });
    }
  }, [door]);
  useEffect(() => { void load(); }, [load]);

  const showOlder = async () => {
    if (!next) return;
    setLoadingOlder(true);
    setOlderProblem(null);
    try {
      const page = await readDoor(door, "announcements_recent", { before: next });
      if (!live.current) return;
      setOlder((current) => [...current, ...page.announcements]);
      setNext(page.next);
    } catch (error) {
      if (live.current) setOlderProblem(`Older announcements could not be read. ${error instanceof Error ? error.message : ""}`.trim());
    } finally {
      if (live.current) setLoadingOlder(false);
    }
  };

  if (first.status === "loading") return <p className="ann-line__quiet">Reading…</p>;
  if (first.status === "problem") return <Problem text={first.text} />;
  const { announcements, overdue } = first.value;
  const unknown = [...announcements, ...older].flatMap((entry) => entry.deliveries).filter((line) => line.attention.some((item) => item.kind === "outcome_unknown")).length;
  return (
    <div className="ann-list" data-announcements-list>
      {overdue.length ? (
        <section className="ann-entry" data-announcements-overdue aria-label="Overdue">
          <header className="ann-entry__head"><strong>Overdue</strong><span className="ann-line__quiet">{overdue.length} {overdue.length === 1 ? "Delivery was" : "Deliveries were"} due and nothing was tried</span></header>
          <ul className="ann-lines">{overdue.map((line) => <DeliveryLineView key={line.id} line={line} />)}</ul>
        </section>
      ) : null}
      {unknown ? <p className="ann-line__quiet" data-announcements-unknown>{unknown} {unknown === 1 ? "Delivery has" : "Deliveries have"} an attempt with no answer yet. Each stays &quot;Outcome unknown&quot; until Caducus settles it.</p> : null}
      {announcements.length + older.length === 0 ? <p className="ann-line__quiet" data-announcements-empty>Nothing has been announced yet.</p> : null}
      {[...announcements, ...older].map((entry) => <AnnouncementView entry={entry} showStories key={entry.id} />)}
      {olderProblem ? <Problem text={olderProblem} /> : null}
      {next ? <button type="button" className="ann-more" disabled={loadingOlder} onClick={() => void showOlder()} data-announcements-older>Show older announcements</button> : null}
    </div>
  );
}
