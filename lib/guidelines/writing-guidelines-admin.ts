/**
 * The logic behind Administration > Policies > Writing guidelines, apart from React: what the editable form holds, how it becomes a guideline document, how each
 * field of a section's effective guidelines is labelled with where it came from, and the client for the guidelines door (`guidelinesRead` and `guidelinesWrite`).
 * Nothing here knows how a document is stored: every read and write is one of the `guidelines_*` operations (docs/plans/guidelines-as-data.md section 8).
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

export const LIST_FIELDS = [
  { key: "tone", label: "Tone", hint: "How the writing should sound. One sentence per line." },
  { key: "sentenceStyle", label: "Sentence style", hint: "How sentences are built. One per line." },
  { key: "voicePatterns", label: "Voice patterns", hint: "Moves the voice makes, and moves it avoids. One per line." },
  { key: "structure", label: "Structure", hint: "How a story is laid out. One per line." },
  { key: "evidenceRules", label: "Evidence rules", hint: "What a claim needs before it is written. One per line." },
] as const;
export const CHOICE_FIELDS = [
  { key: "audience", label: "Audience", hint: "Who the publication writes for." },
  { key: "editorialAim", label: "Editorial aim", hint: "What the writing is for." },
] as const;
export const LOCKABLE_FIELDS: { key: string; label: string }[] = [
  { key: "voice", label: "Voice" }, { key: "audience", label: "Audience" }, { key: "editorialAim", label: "Editorial aim" }, { key: "headline", label: "Headline" }, { key: "glossary", label: "Glossary" },
];
export const FIELD_LABELS: Record<string, string> = {
  voice: "Voice", audience: "Audience", editorialAim: "Editorial aim", headline: "Headline", tone: "Tone", sentenceStyle: "Sentence style", voicePatterns: "Voice patterns",
  structure: "Structure", evidenceRules: "Evidence rules", bodyMarkus: "Guidance in your own words", lexicon: "Words to prefer and avoid", glossary: "Glossary",
  exemplars: "Voice examples", constraints: "Binding rules",
};

export type GlossaryRow = { term: string; use: string; avoid: string };
export type WritingForm = {
  voiceName: string; audience: string; editorialAim: string; lists: Record<string, string>; prefer: string; avoid: string; bodyMarkus: string;
  glossary: GlossaryRow[]; exemplars: { storyLineageId: string; note: string }[]; locked: string[];
};

export const textLines = (text: string): string[] => text.split("\n").map((line) => line.trim()).filter(Boolean);
const joinLines = (items: unknown): string => (Array.isArray(items) ? items.filter((item) => typeof item === "string").join("\n") : "");
const asText = (value: unknown): string => (typeof value === "string" ? value : "");

export function formFromDocument(document: GuidelineDocument | null): WritingForm {
  const source = document ?? {};
  return {
    voiceName: asText(source.voice?.name), audience: asText(source.audience), editorialAim: asText(source.editorialAim),
    lists: Object.fromEntries(LIST_FIELDS.map((field) => [field.key, joinLines(source[field.key])])),
    prefer: joinLines(source.lexicon?.prefer), avoid: joinLines(source.lexicon?.avoid), bodyMarkus: asText(source.bodyMarkus),
    glossary: (Array.isArray(source.glossary) ? source.glossary : []).map((entry: any) => ({ term: asText(entry.term), use: asText(entry.use), avoid: joinLines(entry.avoid).split("\n").join(", ") })),
    exemplars: (Array.isArray(source.exemplars) ? source.exemplars : []).map((entry: any) => ({ storyLineageId: asText(entry.storyLineageId), note: asText(entry.note) })),
    locked: Array.isArray(source.locked) ? source.locked.filter((item: unknown) => typeof item === "string") : [],
  };
}

/**
 * The document a form makes. Fields the form does not edit (headline, binding rules, the legacy publication-only fields) are carried over from `base` untouched;
 * a section's document never carries the publication-only fields, so a section form leaves them out. An empty field is left out, never saved empty.
 */
export function documentFromForm(form: WritingForm, base: GuidelineDocument | null, scope: "publication" | "section"): GuidelineDocument {
  const document: GuidelineDocument = { ...(base ?? {}), schemaVersion: 1 };
  const setOrDrop = (key: string, value: unknown, present: boolean) => { if (present) document[key] = value; else delete document[key]; };
  setOrDrop("voice", { ...(base?.voice ?? {}), name: form.voiceName.trim() }, form.voiceName.trim() !== "");
  setOrDrop("audience", form.audience.trim(), form.audience.trim() !== "");
  setOrDrop("editorialAim", form.editorialAim.trim(), form.editorialAim.trim() !== "");
  for (const field of LIST_FIELDS) { const lines = textLines(form.lists[field.key] ?? ""); setOrDrop(field.key, lines, lines.length > 0); }
  const prefer = textLines(form.prefer), avoid = textLines(form.avoid);
  setOrDrop("lexicon", { ...(prefer.length ? { prefer } : {}), ...(avoid.length ? { avoid } : {}) }, prefer.length + avoid.length > 0);
  setOrDrop("bodyMarkus", form.bodyMarkus, form.bodyMarkus.trim() !== "");
  const glossary = form.glossary.filter((row) => row.term.trim()).map((row) => ({
    term: row.term.trim(), ...(row.use.trim() ? { use: row.use.trim() } : {}), ...(row.avoid.trim() ? { avoid: row.avoid.split(",").map((word) => word.trim()).filter(Boolean) } : {}),
  }));
  setOrDrop("glossary", glossary, glossary.length > 0);
  const exemplars = form.exemplars.filter((row) => row.storyLineageId).map((row) => ({ storyLineageId: row.storyLineageId, ...(row.note.trim() ? { note: row.note.trim() } : {}) }));
  setOrDrop("exemplars", exemplars, exemplars.length > 0);
  if (scope === "publication") setOrDrop("locked", form.locked, form.locked.length > 0);
  else for (const key of ["locked", "constraints", "publicationKey", "judge", "checks", "density", "rules", "compare", "referenceSamples"]) delete document[key];
  return document;
}

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

export const addExemplar = (rows: WritingForm["exemplars"], story: PublishedStory): WritingForm["exemplars"] =>
  rows.some((row) => row.storyLineageId === story.lineageId) ? rows : [...rows, { storyLineageId: story.lineageId, note: "" }];

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
