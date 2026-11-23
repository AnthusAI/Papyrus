import { CheckIcon, CircleHelpIcon, ClockIcon, MinusIcon, PauseIcon, TriangleAlertIcon, XIcon, type LucideIcon } from "lucide-react";
import { OTHER_WORDS, OUTCOME_WORDS, type TodayOutcome } from "@/lib/today-overview";

/**
 * What came of a run, as a Lucide icon and its words (PPY-1a322a). The icons differ by shape, not by colour, and the words are always beside them, so
 * the five outcomes tell apart in greyscale. The server's text mark (`✓ – ? ✗ !`, kept for the command line) is never shown here: `outcomeWords` takes it off.
 */
export const OUTCOME_MARKS: Record<string, LucideIcon> = {
  acted: CheckIcon,
  nothing: MinusIcon,
  asked: CircleHelpIcon,
  failed: XIcon,
  unknown: TriangleAlertIcon,
  notFinished: ClockIcon,
  beforeOutcomes: MinusIcon,
  waiting: PauseIcon,
};

const TEXT_MARK = /^[✓–?✗!]\s+/;

/** The words of an outcome line without the command line's leading text mark. */
export function outcomeWords(shown: string): string {
  return shown.replace(TEXT_MARK, "");
}

export function OutcomeMark({ outcome }: { outcome: string }) {
  const Icon = OUTCOME_MARKS[outcome];
  return Icon ? <Icon aria-hidden="true" className="size-3.5 shrink-0" data-outcome-mark={outcome} /> : null;
}

/** The outcome of one run: its icon (when it has an outcome the table knows) and its words. */
export function RunOutcome({ outcome, shown }: { outcome: string | null; shown: string }) {
  return (
    <span className="inline-flex items-center gap-1.5" data-run-outcome-shown={outcome ?? undefined}>
      {outcome ? <OutcomeMark outcome={outcome} /> : null}
      {outcomeWords(shown)}
    </span>
  );
}

/** What a ProcedureRun record says about how it ended, as the run lists need it. */
export type ProcedureRunOutcomeFields = {
  runStatus: string;
  outcome?: string | null;
  outcomeReason?: string | null;
  waitingFor?: string | null;
  dueAt?: string | null;
};

const FINISHED_STATUSES = new Set(["completed", "failed"]);

/**
 * The outcome of one run read straight from its ProcedureRun record (the console's procedure Recent Runs panel has the record, not the server's outcome line):
 * the key of its icon and its words, by the same rules as `run_outcomes.outcome_shown` on the server. An outcome with its reason; a run that waits for the
 * budget cycle, with why and until when; a finished run with no outcome was recorded before outcomes; any other run is not finished yet.
 */
export function procedureRunOutcome(run: ProcedureRunOutcomeFields): { outcome: string; shown: string } {
  if (run.outcome) {
    const words = OUTCOME_WORDS[run.outcome as TodayOutcome] ?? `Unrecognised outcome (${run.outcome})`;
    return { outcome: run.outcome, shown: run.outcomeReason ? `${words} (${run.outcomeReason})` : words };
  }
  if (run.runStatus === "waiting") {
    return { outcome: "waiting", shown: `Waiting (${run.waitingFor || "no reason recorded"})${run.dueAt ? ` until ${run.dueAt}` : ""}` };
  }
  return FINISHED_STATUSES.has(run.runStatus)
    ? { outcome: "beforeOutcomes", shown: OTHER_WORDS.beforeOutcomes }
    : { outcome: "notFinished", shown: OTHER_WORDS.notFinished };
}
