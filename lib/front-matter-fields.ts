import { parseDocument } from "yaml";
import type { ContentItemVersionRecord } from "./content-item-lifecycle";

/** Front matter keys the editor shows as form fields instead of raw YAML. */
export const FRONT_MATTER_TITLE_KEY = "title";
export const FRONT_MATTER_SUBTITLE_KEY = "deck";
export const FRONT_MATTER_BLURB_KEY = "blurb";

/** Reads one text field from front matter YAML; invalid YAML or a non-text value reads as empty. */
export function readFrontMatterText(frontMatterYaml: string | null | undefined, key: string): string {
  if (!frontMatterYaml?.trim()) return "";
  const document = parseDocument(frontMatterYaml);
  if (document.errors.length) return "";
  const value = document.get(key);
  return typeof value === "string" ? value : "";
}

/** Sets or removes one text field in front matter YAML, keeping every other line and comment as written. */
export function writeFrontMatterText(frontMatterYaml: string | null | undefined, key: string, value: string): string {
  const document = parseDocument(frontMatterYaml?.trim() ? frontMatterYaml : "{}\n");
  if (document.errors.length) return frontMatterYaml ?? "";
  if (value.trim()) document.set(key, value);
  else document.delete(key);
  const text = document.toString();
  return text.trim() === "{}" ? "" : text;
}

function metadataFrontMatterYaml(metadata: unknown): string {
  const parsed = typeof metadata === "string" ? safeJson(metadata) : metadata;
  const text = (parsed as { frontMatterYaml?: unknown } | null)?.frontMatterYaml;
  return typeof text === "string" ? text : "";
}

function safeJson(text: string): unknown {
  try { return JSON.parse(text); } catch { return null; }
}

/** A few lines for a board card: the blurb when one is recorded, else the subtitle. */
export function contentItemExcerpt(version: Pick<ContentItemVersionRecord, "deck" | "metadata">): string | undefined {
  const blurb = readFrontMatterText(metadataFrontMatterYaml(version.metadata), FRONT_MATTER_BLURB_KEY).trim();
  return blurb || version.deck?.trim() || undefined;
}
