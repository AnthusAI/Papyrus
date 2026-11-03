import { parseDocument } from "yaml";
import { getNewsroomNavHref } from "./newsroom-nav";

/**
 * Story variations in the newsroom (docs/story-variations.md): the different ways one idea could connect to what the newsroom knows, side by side.
 * Pure helpers: reading a `StoryVariation` row, where its connections link to, and what accepting one writes onto the Story.
 */

export type VariationStatus = "offered" | "accepted" | "rejected";
export type ConnectionKind = "reference" | "story" | "concept";
export type VariationConnection = { kind: ConnectionKind; id: string; title: string; how: string | null };
export type VariationPointCheck = { verdict: string; claim: string | null; reason: string | null };

export type StoryVariationView = {
  id: string;
  storyLineageId: string;
  variationNumber: number;
  status: VariationStatus;
  point: string;
  headline: string;
  deck: string | null;
  bodyMarkus: string | null;
  section: string | null;
  connections: VariationConnection[];
  origin: string;
  pointCheck: VariationPointCheck | null;
  decidedByLabel: string | null;
  decidedAt: string | null;
  decisionReason: string | null;
};

/** The front matter key that says which variation a Story version's wording came from. */
export const VARIATION_ID_KEY = "variationId";
export const VARIATION_FIELDS = "id storyLineageId variationNumber status point headline deck bodyMarkus section connections origin pointCheck decidedByLabel decidedAt decisionReason";

const KINDS: readonly ConnectionKind[] = ["reference", "story", "concept"];

function json(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value); } catch { return null; }
}

const text = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value : null);

/** A row as the API returns it (`connections` and `pointCheck` are JSON, possibly still a string) read into the shape the pages use. */
export function readVariation(row: Record<string, unknown>): StoryVariationView {
  const connections = json(row.connections);
  const check = json(row.pointCheck) as Record<string, unknown> | null;
  const status = row.status === "accepted" || row.status === "rejected" ? row.status : "offered";
  return {
    id: String(row.id), storyLineageId: String(row.storyLineageId), variationNumber: Number(row.variationNumber ?? 0), status,
    point: String(row.point ?? ""), headline: String(row.headline ?? ""), deck: text(row.deck), bodyMarkus: text(row.bodyMarkus), section: text(row.section),
    connections: (Array.isArray(connections) ? connections : []).flatMap((entry: Record<string, unknown>) => (
      entry && KINDS.includes(entry.kind as ConnectionKind) && text(entry.id) && text(entry.title)
        ? [{ kind: entry.kind as ConnectionKind, id: String(entry.id), title: String(entry.title), how: text(entry.how) }] : [])),
    origin: String(row.origin ?? "generated"), pointCheck: check ? { verdict: String(check.verdict ?? ""), claim: text(check.claim), reason: text(check.reason) } : null,
    decidedByLabel: text(row.decidedByLabel), decidedAt: text(row.decidedAt), decisionReason: text(row.decisionReason),
  };
}

export function sortVariations(rows: readonly StoryVariationView[]): StoryVariationView[] {
  return [...rows].sort((left, right) => left.variationNumber - right.variationNumber);
}

/** Where a connection links: the Reference, the Story (by its lineage id, which is also its first version's id) or the concept. */
export function connectionHref(connection: Pick<VariationConnection, "kind" | "id">, demo = false): string {
  const id = encodeURIComponent(connection.id);
  if (connection.kind === "reference") return getNewsroomNavHref(`/newsroom/references/${id}`, demo);
  if (connection.kind === "story") return getNewsroomNavHref(`/newsroom/articles/${id}`, demo);
  return getNewsroomNavHref(`/newsroom/concepts?node=${id}`, demo);
}

export const CONNECTION_WORDS: Record<ConnectionKind, string> = { reference: "Reference", story: "Story", concept: "Concept" };

/** Whether the earlier accepted variation goes back on offer when another is accepted: it does, the Story has one accepted wording at a time. */
export function acceptedVariation(rows: readonly StoryVariationView[]): StoryVariationView | null {
  return rows.find((row) => row.status === "accepted") ?? null;
}

/**
 * The Story's front matter with a variation's wording on it: the headline as `title`, the deck as `deck`, and `variationId` saying where it came from.
 * Every other line and comment is kept as written. A variation with no deck leaves the Story's deck alone.
 */
export function frontMatterWithVariation(frontMatterYaml: string, variation: Pick<StoryVariationView, "id" | "headline" | "deck">): string {
  const document = parseDocument(frontMatterYaml || "{}\n");
  if (document.errors.length) throw new Error("The front matter could not be read, so the variation was not applied.");
  if (document.contents === null) document.contents = document.createNode({}) as never;
  document.set("title", variation.headline);
  if (variation.deck) document.set("deck", variation.deck);
  document.set(VARIATION_ID_KEY, variation.id);
  return document.toString();
}

/** The variation a Story version's wording came from, or null. */
export function variationIdOf(frontMatterYaml: string | null | undefined): string | null {
  if (!frontMatterYaml?.trim()) return null;
  const document = parseDocument(frontMatterYaml);
  if (document.errors.length) return null;
  const value = document.get(VARIATION_ID_KEY);
  return typeof value === "string" && value ? value : null;
}

/** The body an accepted variation writes: its own when it has one, otherwise the Story's current body. */
export function bodyWithVariation(currentBody: string, variation: Pick<StoryVariationView, "bodyMarkus">): string {
  return variation.bodyMarkus?.trim() ? variation.bodyMarkus : currentBody;
}

export function changeReasonFor(variation: Pick<StoryVariationView, "variationNumber" | "point">): string {
  return `Accepted variation ${variation.variationNumber}: ${variation.point}`.slice(0, 240);
}

export function waysText(count: number): string {
  return count === 1 ? "1 way to connect this" : `${count} ways to connect this`;
}
