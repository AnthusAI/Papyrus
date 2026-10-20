"use client";

import {
  agreementStripState,
  formatPercentage,
  dailyCapWords,
  loopStateWords,
  type AgreementStripMeasurement,
  type ShadowAgreement,
} from "../lib/cyclotron-suggestions";
import { formatSuggestionTime } from "./reference-cyclotron-suggestion";

function MeasurementFigures({ measurement }: { measurement: AgreementStripMeasurement }) {
  const figures: Array<[string, string]> = [
    ["Matches editors", formatPercentage(measurement.agreement)],
    ["Suggested includes editors kept", formatPercentage(measurement.precision)],
    ["Editor includes suggested", formatPercentage(measurement.recall)],
    ["Decisions compared", String(measurement.comparisons)],
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
 * Live agreement at the top of References: how often the
 * suggestions matched what editors then decided. Hidden without a payload.
 */
export function ReferenceLiveAgreement({ agreement }: { agreement: ShadowAgreement | null }) {
  const state = agreementStripState(agreement);
  if (state.kind === "hidden") return null;
  return (
    <section aria-label="Suggestion accuracy" className="shrink-0 space-y-2 border-y border-foreground py-3" data-reference-live-agreement={state.kind}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-foreground">Suggestion accuracy</h3>
      {state.loop ? (
        <p className="text-sm text-foreground" data-reference-live-agreement-loop>
          <span className="font-semibold">{loopStateWords(state.loop)}</span>
          {" · "}Last checked {formatSuggestionTime(state.loop.lastSweepAt)}
          {" · "}{dailyCapWords(state.loop)}
        </p>
      ) : null}
      {state.stopReasonSentence ? (
        <p className="text-sm font-semibold text-foreground" data-reference-live-agreement-stopped>{state.stopReasonSentence}</p>
      ) : null}
      {state.kind === "not_enough" ? (
        <p className="text-sm text-foreground" data-reference-live-agreement-not-enough>
          Not enough decisions yet: {state.measurement.comparisons} of {state.needed} editor decisions have followed a suggestion. Figures appear at {state.needed}.
        </p>
      ) : <MeasurementFigures measurement={state.measurement} />}
      <p className="text-xs text-foreground">
        Suggestions compared with the decisions editors made afterwards. Updated {formatSuggestionTime(agreement?.computedAt ?? null)}.
      </p>
    </section>
  );
}
