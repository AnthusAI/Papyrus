"use client";

import { formatPercentage } from "../lib/cyclotron-suggestions";
import { sectionAgreementIsMeasured, type SectionAgreement, type SectionSuggestion, type SiteSectionAgreement } from "../lib/site-section-suggestions";
import { MINIMUM_COMPARISONS_FOR_AGREEMENT } from "../lib/cyclotron-suggestions";

export type SectionChoice = { id: string; title: string };

function titleOf(sections: SectionChoice[], sectionId: string): string {
  return sections.find((section) => section.id === sectionId)?.title ?? sectionId;
}

function agreementWords(agreement: SectionAgreement | undefined): string {
  if (!agreement) return "no editor decisions compared yet";
  if (!sectionAgreementIsMeasured(agreement)) {
    return `${agreement.comparisons} of ${MINIMUM_COMPARISONS_FOR_AGREEMENT} editor decisions compared, too few to measure`;
  }
  return `agreement ${formatPercentage(agreement.agreement)}, ${agreement.comparisons} editor decisions compared`;
}

/**
 * The suggested Section for a pending reference, how likely the other Sections
 * are, and how often this Section's suggestions matched editors. Advisory: no
 * Section is chosen until an editor picks one.
 */
export function SectionSuggestionBlock({
  agreement,
  referenceLineageId,
  sections,
  suggestion,
}: {
  agreement: SiteSectionAgreement | null;
  referenceLineageId: string;
  sections: SectionChoice[];
  suggestion: SectionSuggestion;
}) {
  const figures = agreement?.sections.find((entry) => entry.sectionId === suggestion.sectionId);
  const others = suggestion.probabilities.filter((entry) => entry.sectionId !== suggestion.sectionId).slice(0, 3);
  return (
    <section aria-label="Suggested Section" className="space-y-2 border-y border-foreground py-3" data-reference-section-suggestion={referenceLineageId}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-foreground">Suggested Section</h3>
      <p className="text-sm text-foreground">
        The cyclotron suggests <span className="font-semibold">{titleOf(sections, suggestion.sectionId)}</span>
        {suggestion.confidence !== null ? ` (${formatPercentage(suggestion.confidence)})` : ""}.
      </p>
      {others.length ? (
        <p className="text-xs text-foreground" data-reference-section-alternatives>
          Next most likely: {others.map((entry) => `${titleOf(sections, entry.sectionId)} ${formatPercentage(entry.probability)}`).join(", ")}.
        </p>
      ) : null}
      <p className="text-xs text-foreground" data-reference-section-agreement>
        For {titleOf(sections, suggestion.sectionId)}: {agreementWords(figures)}.
      </p>
      <p className="text-xs text-foreground" data-reference-section-notice>
        A suggestion never places a reference. The Section you choose when you accept does.
      </p>
    </section>
  );
}

/**
 * Picks the Section an accepted reference belongs to. The choice is sent with
 * the accept and is what the cyclotron learns from; nothing is preselected.
 */
export function SectionPicker({
  agreement,
  chosenSectionId,
  disabled,
  onChoose,
  referenceLineageId,
  sections,
  suggestedSectionId,
}: {
  agreement: SiteSectionAgreement | null;
  chosenSectionId: string | null;
  disabled?: boolean;
  onChoose: (sectionId: string | null) => void;
  referenceLineageId: string;
  sections: SectionChoice[];
  suggestedSectionId: string | null;
}) {
  return (
    <fieldset className="space-y-1 border-l-2 border-foreground pl-3" data-reference-section-picker={referenceLineageId} disabled={disabled}>
      <legend className="text-xs font-semibold uppercase tracking-wide text-foreground">Section when you accept</legend>
      <label className="flex items-center gap-2 text-sm text-foreground">
        <input checked={chosenSectionId === null} name={`section-${referenceLineageId}`} onChange={() => onChoose(null)} type="radio" />
        <span className={chosenSectionId === null ? "font-semibold" : undefined}>No Section</span>
      </label>
      {sections.map((section) => {
        const figures = agreement?.sections.find((entry) => entry.sectionId === section.id);
        const chosen = chosenSectionId === section.id;
        return (
          <label className="flex flex-wrap items-center gap-x-2 text-sm text-foreground" key={section.id}>
            <input checked={chosen} name={`section-${referenceLineageId}`} onChange={() => onChoose(section.id)} type="radio" value={section.id} />
            <span className={chosen ? "font-semibold underline underline-offset-4" : undefined}>{section.title}</span>
            {section.id === suggestedSectionId ? <span className="text-xs">suggested</span> : null}
            {sectionAgreementIsMeasured(figures) ? <span className="text-xs">agreement {formatPercentage(figures?.agreement ?? null)}</span> : null}
          </label>
        );
      })}
      <p className="text-xs text-foreground">The Section you choose is saved with your decision.</p>
    </fieldset>
  );
}
