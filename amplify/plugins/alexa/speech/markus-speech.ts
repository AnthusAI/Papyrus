/**
 * Turns a Markus document into speech by walking its `MarkusDocument` nodes (lib/markus-ir.ts), never its text. The result is a list
 * of SSML units (sentences, headings and pauses) that `fitUnits` can cut at a boundary.
 */
import type { MarkusBlock, MarkusDocument, MarkusInline, MarkusNode } from "../../../../lib/markus-ir";
import { parseMarkusDocument } from "../../../../lib/markus-ir";
import { parseMarkusSource } from "../content/markus-source";
import type { PublicStory } from "../contracts";
import { collapseWhitespace, escapeSsml, pause, sentence, splitSentences } from "./ssml";

const PARAGRAPH_PAUSE = pause(400);
const TOKEN_PATTERN = /PAPYRUSMARKUP\d{5}END/g;
/** Directives whose content repeats the body or is only for the eye. */
const SILENT_DIRECTIVES = new Set(["pull-quote", "image", "figure", "video", "metric"]);

export function inlineText(nodes: readonly MarkusInline[]): string {
  let text = "";
  for (const node of nodes) {
    switch (node.type) {
      case "text":
        text += node.text;
        break;
      case "emphasis":
      case "strong":
      case "strikethrough":
      case "link":
        text += inlineText(node.children);
        break;
      case "code_span":
        text += node.code;
        break;
      case "soft_break":
      case "hard_break":
        text += " ";
        break;
      default:
        break; // images and raw HTML are not spoken
    }
  }
  return collapseWhitespace(text.replace(TOKEN_PATTERN, ""));
}

function sentencesOf(text: string): string[] {
  return splitSentences(text).map(sentence);
}

function blockUnits(block: MarkusBlock): string[] {
  switch (block.type) {
    case "heading": {
      const text = inlineText(block.inline);
      return text ? [pause(500), `<s><emphasis level="moderate">${escapeSsml(text)}</emphasis></s>`, pause(300)] : [];
    }
    case "paragraph": {
      const units = sentencesOf(inlineText(block.inline));
      return units.length > 0 ? [...units, PARAGRAPH_PAUSE] : [];
    }
    case "list":
      return block.items.flatMap((item) => item.children.flatMap(blockUnits));
    case "blockquote":
      return block.children.flatMap(nodeUnits);
    case "code":
      return [sentence("There is a code example on the page."), PARAGRAPH_PAUSE];
    case "table":
      return [sentence("There is a table on the page."), PARAGRAPH_PAUSE];
    case "thematic_break":
      return [pause(600)];
    default:
      return []; // raw HTML blocks
  }
}

function nodeUnits(node: MarkusNode): string[] {
  if (node.type !== "directive") return blockUnits(node);
  if (SILENT_DIRECTIVES.has(node.name)) return [];
  const title = typeof node.attributes.title === "string" ? sentencesOf(node.attributes.title) : [];
  return [...title, ...node.children.flatMap(nodeUnits)];
}

export function documentUnits(document: MarkusDocument): string[] {
  return document.children.flatMap(nodeUnits);
}

/** The document a story reads from: the stored `bodyIr` (an envelope or a bare document) when present, else its Markus source. */
export function storyDocument(story: Pick<PublicStory, "markus" | "bodyIr">): MarkusDocument {
  let raw = story.bodyIr;
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      raw = undefined;
    }
  }
  if (typeof raw === "object" && raw !== null) {
    const candidate = (raw as { document?: unknown }).document ?? raw;
    return parseMarkusDocument(candidate);
  }
  return parseMarkusSource(story.markus);
}

export function storyBodyUnits(story: Pick<PublicStory, "markus" | "bodyIr">): string[] {
  return documentUnits(storyDocument(story));
}

function blockText(block: MarkusBlock): string[] {
  switch (block.type) {
    case "heading":
    case "paragraph": {
      const text = inlineText(block.inline);
      return text ? [text] : [];
    }
    case "list":
      return block.items.flatMap((item) => item.children.flatMap(blockText));
    case "blockquote":
      return block.children.flatMap(nodeText);
    default:
      return []; // code, tables, rules and raw HTML stay on the web page
  }
}

function nodeText(node: MarkusNode): string[] {
  if (node.type !== "directive") return blockText(node);
  if (SILENT_DIRECTIVES.has(node.name)) return [];
  const title = typeof node.attributes.title === "string" && node.attributes.title.trim() ? [collapseWhitespace(node.attributes.title)] : [];
  return [...title, ...node.children.flatMap(nodeText)];
}

/** The story body as plain paragraphs, for the screen: the same nodes the speech reads, without SSML. */
export function storyParagraphs(story: Pick<PublicStory, "markus" | "bodyIr">): string[] {
  return storyDocument(story).children.flatMap(nodeText);
}
