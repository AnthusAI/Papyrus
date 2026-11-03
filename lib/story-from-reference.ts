import { parseDocument } from "yaml";

/**
 * Create Story: the pieces the editor and the local preview share with the backend action (`src/papyrus_content/story_from_reference.py`,
 * `create_story_from_reference`). The real story is built on the server; these only describe it, and build the same draft for the preview.
 */

export const SEEDED_FROM_KEY = "seededFrom";
export const SEEDED_IMAGE_KEY = "seededImage";

export type SeededFrom = { summary: "included" | "none" | "withheld"; imageCredit: string | null; imageUrl: string | null };

function readKey(frontMatterYaml: string | null | undefined, key: string): Record<string, unknown> | null {
  if (!frontMatterYaml?.trim()) return null;
  const document = parseDocument(frontMatterYaml);
  if (document.errors.length) return null;
  const value = (document.get(key) as { toJSON?: () => unknown } | null)?.toJSON?.();
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

/** Whether the story was started by Create Story, and what it was started from. */
export function readSeededFrom(frontMatterYaml: string | null | undefined): SeededFrom | null {
  const seeded = readKey(frontMatterYaml, SEEDED_FROM_KEY);
  if (!seeded) return null;
  const image = readKey(frontMatterYaml, SEEDED_IMAGE_KEY);
  const summary = seeded.summary === "included" || seeded.summary === "withheld" ? seeded.summary : "none";
  return { summary, imageCredit: typeof image?.credit === "string" ? image.credit : null, imageUrl: typeof image?.url === "string" ? image.url : null };
}

/** `Source: [title](address), site.`: the link and who it came from, never the source's own text. */
export function sourceAttribution(title: string, url: string | null, site: string | null): string {
  const clean = title.replace(/\s+/g, " ").replace(/\[/g, "(").replace(/\]/g, ")").trim() || url || "the source";
  return `Source: ${url ? `[${clean}](${url})` : clean}${site ? `, ${site}.` : "."}`;
}

/** The body Create Story starts from: the summary, then the source line; the source line alone when there is no summary. */
export function startBody(summary: string | null, attribution: string): string {
  const text = (summary ?? "").replace(/\s+/g, " ").trim();
  return `${text ? `${text}\n\n` : ""}${attribution}\n`;
}

function attribute(value: string): string {
  return value.replace(/"/g, "'").replace(/\}/g, ")").replace(/\s+/g, " ").trim();
}

/** The `::image` line that seeds the draft: the source's own address (never copied to our media), credited to its site. */
export function seededImageLine(url: string, title: string, site: string | null): string {
  return `::image{src="${url}" alt="${attribute(title || "Preview image")}"${site ? ` credit="${attribute(`Image: ${site}`)}"` : ""}}`;
}

/** The button's caption for a Reference in this status: a rejected Reference says so, because creating a story never overturns the vote. */
export function createStoryCaption(status: string, automatic = false): { label: string; note: string | null } {
  if (automatic && status === "accepted") return { label: "Create Story", note: "Also confirms the automatic acceptance." };
  if (status === "rejected") return { label: "Create Story", note: "This Reference is rejected. Its vote stays." };
  if (status === "pending") return { label: "Create Story", note: "Also accepts this Reference." };
  return { label: "Create Story", note: null };
}
