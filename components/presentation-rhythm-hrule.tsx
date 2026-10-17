type PresentationRhythmHRuleProps = {
  /** Hide in wide 2-column secondary pairs (items 1+2 side-by-side). */
  hideInSecondaryPair?: boolean;
};

export function PresentationRhythmHRule({ hideInSecondaryPair = false }: PresentationRhythmHRuleProps) {
  return (
    <div
      aria-hidden="true"
      className="presentation-rhythm-hrule"
      data-hide-in-secondary-pair={hideInSecondaryPair ? "true" : undefined}
      role="presentation"
    >
      <div className="presentation-rhythm-hrule__line" />
    </div>
  );
}
