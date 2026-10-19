import type { SemanticRelationRecord } from "./category-repository";
import { MINIMUM_COMPARISONS_FOR_AGREEMENT, SHADOW_AGREEMENT_SCHEMA } from "./cyclotron-suggestions";

export const SITE_DECISION_RELATION = "site_decision_is";
export const SECTION_SELECTOR_CLASSIFIER_PREFIX = "section-selector-";
export const SECTION_FIT_CLASSIFIER_PREFIX = "section-fit-";

/** The site cyclotron's suggested Section for one reference. Advisory only. */
export type SectionSuggestion = {
  decisionRelationId: string;
  cyclotronId: string | null;
  sectionId: string;
  confidence: number | null;
  /** Section id to probability, highest first. */
  probabilities: Array<{ sectionId: string; probability: number }>;
  decidedAt: string | null;
};

/** How often the suggestion of one Section matched what editors later decided. */
export type SectionAgreement = {
  sectionId: string;
  comparisons: number;
  agreement: number | null;
  precision: number | null;
  recall: number | null;
};

export type SiteSectionAgreement = {
  computedAt: string | null;
  selectorAccuracy: number | null;
  selectorComparisons: number;
  sections: SectionAgreement[];
};

function parseMetadata(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The part of `<cyclotronId>/<classifier>` after the last slash. */
export function siteClassifierName(classifierKey: string): string {
  return classifierKey.slice(classifierKey.lastIndexOf("/") + 1);
}

/**
 * Current suggested Sections keyed by reference lineage, from the relations the
 * Newsroom already loads. Only the section-selector classifier names a Section.
 */
export function currentSectionSuggestions(relations: SemanticRelationRecord[]): Map<string, SectionSuggestion> {
  const suggestions = new Map<string, SectionSuggestion>();
  for (const relation of relations) {
    if (relation.predicate !== SITE_DECISION_RELATION || relation.relationState !== "current") continue;
    if (!siteClassifierName(relation.classifierId ?? "").startsWith(SECTION_SELECTOR_CLASSIFIER_PREFIX)) continue;
    const metadata = parseMetadata(relation.metadata);
    const sectionId = typeof metadata.label === "string" ? metadata.label : "";
    if (!sectionId) continue;
    const rawProbabilities = parseMetadata(metadata.probabilities);
    const probabilities = Object.entries(rawProbabilities)
      .flatMap(([candidate, probability]) => (numberOrNull(probability) === null ? [] : [{ sectionId: candidate, probability: probability as number }]))
      .sort((left, right) => right.probability - left.probability);
    suggestions.set(relation.subjectLineageId, {
      decisionRelationId: relation.id,
      cyclotronId: typeof metadata.cyclotronId === "string" ? metadata.cyclotronId : null,
      sectionId,
      confidence: numberOrNull(relation.confidence) ?? probabilities.find((entry) => entry.sectionId === sectionId)?.probability ?? null,
      probabilities,
      decidedAt: typeof metadata.decidedAt === "string" ? metadata.decidedAt : null,
    });
  }
  return suggestions;
}

/** The site cyclotron's id, from any current Section suggestion. */
export function siteCyclotronIdOf(suggestions: Map<string, SectionSuggestion>): string | null {
  for (const suggestion of suggestions.values()) if (suggestion.cyclotronId) return suggestion.cyclotronId;
  return null;
}

/** The per-Section part of a cyclotron-shadow-agreement/v1 payload the site sweep wrote, or null for any other JSON. */
export function parseSiteSectionAgreement(json: unknown): SiteSectionAgreement | null {
  if (!json || typeof json !== "object") return null;
  const record = json as Record<string, unknown>;
  if (record.schema !== SHADOW_AGREEMENT_SCHEMA) return null;
  const classifiers = record.classifiers;
  if (!classifiers || typeof classifiers !== "object") return null;
  const sections: SectionAgreement[] = [];
  for (const [classifier, value] of Object.entries(classifiers as Record<string, unknown>)) {
    if (!classifier.startsWith(SECTION_FIT_CLASSIFIER_PREFIX) || !value || typeof value !== "object") continue;
    const metrics = value as Record<string, unknown>;
    sections.push({
      sectionId: classifier.slice(SECTION_FIT_CLASSIFIER_PREFIX.length),
      comparisons: numberOrNull(metrics.comparisons) ?? 0,
      agreement: numberOrNull(metrics.agreement),
      precision: numberOrNull(metrics.precision),
      recall: numberOrNull(metrics.recall),
    });
  }
  if (!sections.length && numberOrNull(record.selectorAccuracy) === null) return null;
  return {
    computedAt: typeof record.computedAt === "string" ? record.computedAt : null,
    selectorAccuracy: numberOrNull(record.selectorAccuracy),
    selectorComparisons: numberOrNull(record.comparisons) ?? 0,
    sections,
  };
}

/** Agreement figures are worth showing only once enough editor decisions followed a suggestion. */
export function sectionAgreementIsMeasured(agreement: SectionAgreement | undefined): boolean {
  return Boolean(agreement) && (agreement as SectionAgreement).comparisons >= MINIMUM_COMPARISONS_FOR_AGREEMENT && (agreement as SectionAgreement).agreement !== null;
}
