import type { ReferenceRecord, SemanticRelationRecord } from "./category-repository";
import { SHADOW_AGREEMENT_SCHEMA } from "./cyclotron-suggestions";
import { SECTION_FIT_CLASSIFIER_PREFIX, SECTION_SELECTOR_CLASSIFIER_PREFIX, parseSiteSectionAgreement, type SiteSectionAgreement } from "./site-section-suggestions";

const PREVIEW_SITE_CYCLOTRON_ID = "preview-site-cyclotron";

/**
 * Local preview only: a suggested Section on the first pending references and
 * a measured agreement for each Section, so the References screen can be
 * reviewed without a sweep.
 */
export function createLocalPreviewSectionFixtures(
  references: ReferenceRecord[],
  sectionIds: string[],
): { relations: SemanticRelationRecord[]; agreement: SiteSectionAgreement | null } {
  if (sectionIds.length < 2) return { relations: [], agreement: null };
  const relations: SemanticRelationRecord[] = references.slice(0, 6).map((reference, index) => {
    const lineageId = reference.lineageId ?? reference.id;
    const top = sectionIds[index % sectionIds.length];
    const runnerUp = sectionIds[(index + 1) % sectionIds.length];
    const confidence = 0.88 - index * 0.07;
    const probabilities: Record<string, number> = { [top]: confidence, [runnerUp]: (1 - confidence) * 0.7 };
    const rest = sectionIds.filter((candidate) => candidate !== top && candidate !== runnerUp);
    rest.forEach((candidate) => { probabilities[candidate] = (1 - confidence) * 0.3 / rest.length; });
    return {
      id: `preview-section-relation-${index}`,
      relationState: "current",
      predicate: "site_decision_is",
      subjectKind: "reference",
      subjectId: reference.id,
      subjectLineageId: lineageId,
      objectKind: "semanticNode",
      objectId: `semantic-node-site-${top}-v1`,
      objectLineageId: `semantic-node-site-${top}`,
      subjectStateKey: `reference#${lineageId}#current`,
      objectStateKey: `semanticNode#semantic-node-site-${top}#current`,
      objectSubjectStateKey: `semanticNode#semantic-node-site-${top}#current#reference`,
      predicateObjectStateKey: `site_decision_is#semanticNode#semantic-node-site-${top}#current`,
      subjectVersionKey: `reference#${reference.id}`,
      objectVersionKey: `semanticNode#semantic-node-site-${top}-v1`,
      confidence,
      classifierId: `${PREVIEW_SITE_CYCLOTRON_ID}/${SECTION_SELECTOR_CLASSIFIER_PREFIX}preview`,
      modelVersion: "2",
      reviewRecommended: false,
      metadata: JSON.stringify({
        decisionId: `preview-site-decision-${index}`,
        cyclotronId: PREVIEW_SITE_CYCLOTRON_ID,
        classifier: `${SECTION_SELECTOR_CLASSIFIER_PREFIX}preview`,
        label: top,
        probabilities,
        version: 2,
        decidedAt: new Date(Date.UTC(2026, 9, 18, 6 - index)).toISOString(),
      }),
    } as SemanticRelationRecord;
  });
  const classifiers: Record<string, unknown> = { [`${SECTION_SELECTOR_CLASSIFIER_PREFIX}preview`]: { comparisons: 14, correct: 10, agreement: 10 / 14 } };
  sectionIds.forEach((sectionId, index) => {
    classifiers[`${SECTION_FIT_CLASSIFIER_PREFIX}${sectionId}`] = index === sectionIds.length - 1
      ? { comparisons: 4, agreement: 0.75, precision: 0.5, recall: 1 }
      : { comparisons: 12 + index, agreement: 0.9 - index * 0.08, precision: 0.85 - index * 0.06, recall: 0.8 };
  });
  return {
    relations,
    agreement: parseSiteSectionAgreement({
      schema: SHADOW_AGREEMENT_SCHEMA,
      computedAt: "2026-10-18T09:00:00.000Z",
      comparisons: 14,
      selectorAccuracy: 10 / 14,
      classifiers,
    }),
  };
}
