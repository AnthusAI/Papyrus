/**
 * The logic behind Administration > Policies > Writing guidelines, apart from React: the types of the guidelines door, how each field of a section's effective
 * guidelines is labelled with where it came from, change lines, and the checks drawn from a set. The files editor itself is `guideline-files.ts`. Nothing here
 * knows how a set is stored: every read and write is one of the `guidelines_*` operations (docs/plans/guidelines-as-data.md section 8).
 */
import type { ImageEnvelope, ImageOperationName, ImageOperations } from "../images/operations.generated";

export type GuidelineDocument = Record<string, any>;
export type GuidelinesOperationName = Extract<ImageOperationName, `guidelines_${string}`>;
export type GuidelinesDoor = <Name extends GuidelinesOperationName>(op: Name, input: ImageOperations[Name]["input"]) => Promise<ImageEnvelope<ImageOperations[Name]["result"]>>;
export type PublishedStory = { lineageId: string; title: string };
export type ListPublishedStories = () => Promise<PublishedStory[]>;
export type SourceLayer = { layer: "publication" | "section"; version?: number | null };
export type FieldSources = Record<string, SourceLayer[]>;

export const SITE_TAB = "site";
export const NO_REASON_PROBLEM = "Say why you are changing the guidelines. The reason is kept with who changed them and when.";
export const NO_WRITING_WARNING = "This publication has no writing guidelines yet, so agents and the editorial checks have no house voice to follow. Write them here.";
export const EDITORS_READ_ONLY = "You can read the writing guidelines. Only an admin can change them.";

export const FIELD_LABELS: Record<string, string> = {
  voice: "Voice", audience: "Audience", editorialAim: "Editorial aim", headline: "Headline", tone: "Tone", sentenceStyle: "Sentence style", voicePatterns: "Voice patterns",
  structure: "Structure", evidenceRules: "Evidence rules", bodyMarkus: "Guidance in your own words", lexicon: "Words to prefer and avoid", glossary: "Glossary",
  exemplars: "Voice examples", constraints: "Binding rules",
};

export function reasonProblem(reason: string): string | null {
  return reason.trim() ? null : NO_REASON_PROBLEM;
}

/** True for a field the site locks, so a section tab cannot change it. */
export const isLocked = (siteDocument: GuidelineDocument | null, field: string): boolean => Array.isArray(siteDocument?.locked) && siteDocument!.locked.includes(field);

/** Where a field of the effective guidelines came from, in words: never colour alone. */
export function sourceWords(field: string, sources: FieldSources | null | undefined, siteDocument: GuidelineDocument | null, isSection: boolean): string {
  if (isSection && isLocked(siteDocument, field)) return "Locked by site";
  const layers = (sources?.[field] ?? []).map((entry) => entry.layer);
  if (layers.includes("section") && layers.includes("publication")) return "Site and this section";
  if (layers.includes("section")) return "This section";
  return "Site";
}

export function describeChange(change: { path: string; from?: unknown; to?: unknown }): string {
  const top = change.path.split(/[.[]/)[0];
  const name = FIELD_LABELS[top] ?? change.path;
  const shown = (value: unknown) => (typeof value === "string" ? `"${value}"` : JSON.stringify(value));
  if (change.from === undefined) return `${name}: added ${shown(change.to)}`;
  if (change.to === undefined) return `${name}: removed ${shown(change.from)}`;
  return `${name}: changed from ${shown(change.from)} to ${shown(change.to)}`;
}

export function storyTitle(stories: PublishedStory[], lineageId: string): string {
  return stories.find((story) => story.lineageId === lineageId)?.title ?? lineageId;
}

export const matchStories = (stories: PublishedStory[], query: string): PublishedStory[] => {
  const needle = query.trim().toLowerCase();
  return (needle ? stories.filter((story) => story.title.toLowerCase().includes(needle)) : stories).slice(0, 8);
};

/** What differs between two versions of a document, field by field, as the change lines the save preview uses. */
export function diffDocuments(older: GuidelineDocument, newer: GuidelineDocument): { path: string; from?: unknown; to?: unknown }[] {
  const keys = [...new Set([...Object.keys(older), ...Object.keys(newer)])].filter((key) => key !== "schemaVersion").sort();
  return keys.filter((key) => JSON.stringify(older[key]) !== JSON.stringify(newer[key])).map((key) => ({ path: key, from: older[key], to: newer[key] }));
}

export const DERIVED_SOURCE_PREFIX = "writing-guidelines:";

/** The slug a writing document's lineage uses, as the derived checks name it in their source. */
export const writingSlug = (section: string | null): string =>
  section ? `desk-doctrine-${section.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "topic"}-writing` : "editorial-doctrine-writing";

export function derivedChecks<T extends { source: string }>(policies: T[], section: string | null): T[] {
  const prefix = `${DERIVED_SOURCE_PREFIX}${writingSlug(section)}:v`;
  return policies.filter((policy) => policy.source.startsWith(prefix));
}

/** A short plain-words value for the effective view. */
export function valueWords(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((item) => (typeof item === "string" ? item : item?.term ?? item?.storyLineageId ?? item?.text ?? JSON.stringify(item))).join("; ");
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.name === "string") return record.name;
    return Object.entries(record).map(([key, item]) => `${key}: ${valueWords(item)}`).join(" | ");
  }
  return String(value);
}
