"use client";

import {
  curationForSuggestionChoice,
  provenanceSummary,
  suggestionConfidenceWords,
  type SuggestionChoice,
} from "../lib/cyclotron-suggestions";
import type { RelevanceCuration, RelevanceDecisionView } from "../lib/relevance-decisions";

const RULE_BUTTON_CLASS =
  "border border-foreground px-3 py-1 text-sm font-semibold text-foreground underline-offset-4 hover:underline disabled:cursor-not-allowed disabled:opacity-100 disabled:line-through";

/** UTC and fixed-format so server and browser render the same words. */
export function formatSuggestionTime(instant: string | null): string {
  if (!instant) return "time not recorded";
  const parsed = new Date(instant);
  if (Number.isNaN(parsed.getTime())) return "time not recorded";
  return `${parsed.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

/** The one-line suggestion in a queue row. Never worded as a decision. */
export function ReferenceSuggestionRowLine({
  decision,
  referenceLineageId,
}: {
  decision: RelevanceDecisionView;
  referenceLineageId: string;
}) {
  return (
    <p className="mt-1 text-xs text-foreground" data-reference-suggestion-row={referenceLineageId}>
      <span className="font-semibold">Suggestion:</span> {decision.label}, {suggestionConfidenceWords(decision)}
    </p>
  );
}

/**
 * The detail's Suggestion block. Agree and Overrule go through the ordinary
 * accept and reject actions; nothing changes until an editor clicks.
 */
export function ReferenceSuggestionBlock({
  decision,
  disabled,
  onCurate,
  referenceLineageId,
  statusLabel,
  settled,
}: {
  decision: RelevanceDecisionView;
  disabled?: boolean;
  onCurate?: (curation: RelevanceCuration) => void;
  referenceLineageId: string;
  statusLabel: string;
  settled: boolean;
}) {
  const choose = (choice: SuggestionChoice) => onCurate?.(curationForSuggestionChoice(decision, choice));
  const suggestsAccept = decision.positiveLabel !== null && decision.label === decision.positiveLabel;
  return (
    <section aria-label="Suggestion" className="space-y-2 border-y border-foreground py-3" data-reference-suggestion={referenceLineageId}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-foreground">Suggestion</h3>
      <p className="text-sm text-foreground">
        The cyclotron suggests <span className="font-semibold">{decision.label}</span> ({suggestionConfidenceWords(decision)}).
      </p>
      <p className="text-xs text-foreground" data-reference-suggestion-notice>
        A suggestion never changes the status until an editor acts. This reference is {statusLabel.toLowerCase()}.
      </p>
      {!settled && onCurate ? (
        <div className="flex flex-wrap gap-2">
          <button
            className={RULE_BUTTON_CLASS}
            data-reference-suggestion-agree
            disabled={disabled}
            onClick={() => choose("agree")}
            type="button"
          >
            Agree ({suggestsAccept ? "accept" : "reject"})
          </button>
          <button
            className={RULE_BUTTON_CLASS}
            data-reference-suggestion-overrule
            disabled={disabled}
            onClick={() => choose("overrule")}
            type="button"
          >
            Overrule ({suggestsAccept ? "reject" : "accept"})
          </button>
        </div>
      ) : null}
    </section>
  );
}

/** The expandable "How this suggestion was made" block, from the recorded provenance. */
export function ReferenceSuggestionProvenance({ decision }: { decision: RelevanceDecisionView }) {
  const summary = provenanceSummary(decision);
  return (
    <details className="text-sm text-foreground" data-reference-suggestion-provenance>
      <summary className="cursor-pointer font-semibold underline-offset-4 hover:underline">How this suggestion was made</summary>
      {summary ? (
        <ul className="mt-2 space-y-1">
          <li>{summary.teachingLabelsSentence}.</li>
          <li>{summary.primingExamplesSentence}.</li>
          <li>Doctrine fingerprint {summary.doctrineShortHash ?? "not recorded"}.</li>
          <li>Model {summary.modelVersion ?? "version not recorded"}.</li>
          <li>Decided {formatSuggestionTime(summary.decidedAt)}.</li>
        </ul>
      ) : (
        <p className="mt-2">This suggestion was made before the cyclotron recorded how. Only its model version and confidence are known.</p>
      )}
    </details>
  );
}

/** Shown only when the latest curation of the reference was made by a signed-in person. */
export function CountsAsTrainingLabelNote({ referenceLineageId }: { referenceLineageId: string }) {
  return (
    <p className="border-l-2 border-foreground pl-2 text-xs font-semibold text-foreground" data-reference-training-label={referenceLineageId}>
      Counts as a training label: an editor made this decision, so the cyclotron learns from it.
    </p>
  );
}
