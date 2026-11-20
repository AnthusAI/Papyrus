import { CheckIcon, CircleHelpIcon, ClockIcon, MinusIcon, TriangleAlertIcon, XIcon, type LucideIcon } from "lucide-react";

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
