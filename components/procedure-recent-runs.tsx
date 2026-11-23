import type { ProcedureRunRecord } from "@/lib/category-repository";
import { RunOutcome, procedureRunOutcome } from "./run-outcome";

/** The rows of a procedure's Recent Runs panel: each run's outcome as its Lucide icon and words (never colour alone), then when it was asked for and which attempt. */
export function ProcedureRecentRunList({ runs }: { runs: ProcedureRunRecord[] }) {
  return (
    <dl>
      {runs.map((run) => {
        const { outcome, shown } = procedureRunOutcome(run);
        return (
          <div key={run.id} data-procedure-run={run.id}>
            <dt><RunOutcome outcome={outcome} shown={shown} /></dt>
            <dd>{run.requestedAt ?? "-"} / attempt {run.attempt ?? 1}</dd>
          </div>
        );
      })}
    </dl>
  );
}
