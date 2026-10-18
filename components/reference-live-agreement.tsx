"use client";

import {
  agreementStripState,
  formatPercentage,
  stopReasonSentence,
  type AgreementStripMeasurement,
  type ShadowAgreement,
} from "../lib/cyclotron-suggestions";
import { formatSuggestionTime } from "./reference-cyclotron-suggestion";

function MeasurementFigures({ measurement }: { measurement: AgreementStripMeasurement }) {
  const figures: Array<[string, string]> = [
    ["Agreement", formatPercentage(measurement.agreement)],
    ["Precision", formatPercentage(measurement.precision)],
    ["Recall", formatPercentage(measurement.recall)],
    ["Comparisons", String(measurement.comparisons)],
  ];
  return (
    <dl className="flex flex-wrap gap-x-6 gap-y-1">
      {figures.map(([name, value]) => (
        <div key={name}>
          <dt className="text-xs font-semibold uppercase tracking-wide text-foreground">{name}</dt>
          <dd className="text-base font-semibold text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Live agreement at the top of References: how often the cyclotron's
 * suggestions matched what editors then decided. Hidden without a payload.
 */
export function ReferenceLiveAgreement({ agreement }: { agreement: ShadowAgreement | null }) {
  const state = agreementStripState(agreement);
  if (state.kind === "hidden") return null;
  return (
    <section aria-label="Live agreement" className="shrink-0 space-y-2 border-y border-foreground py-3" data-reference-live-agreement={state.kind}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-foreground">Live agreement</h3>
      {state.kind === "stopped" ? (
        <p className="text-sm font-semibold text-foreground" data-reference-live-agreement-stopped>{stopReasonSentence(state.reason)}</p>
      ) : null}
      {state.kind === "not_enough" ? (
        <p className="text-sm text-foreground" data-reference-live-agreement-not-enough>
          Not enough comparisons yet: {state.comparisons} of {state.needed} editor decisions have followed a suggestion. Figures appear at {state.needed}.
        </p>
      ) : null}
      {state.kind === "measured" ? <MeasurementFigures measurement={state.measurement} /> : null}
      {state.kind === "stopped" && state.measurement ? <MeasurementFigures measurement={state.measurement} /> : null}
      <p className="text-xs text-foreground">
        Suggestions compared with the decisions editors made afterwards. Computed {formatSuggestionTime(agreement?.computedAt ?? null)}.
      </p>
    </section>
  );
}
