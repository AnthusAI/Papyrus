/**
 * The Pretext projection: turns a typed Markus document IR
 * (`lib/markus-ir.ts`) into the flat structures the Pretext client solver
 * consumes today -- `Article.body: string[]`, `Article.pullQuotes: string[]`,
 * and figure-derived `ArticleImageAsset[]`.
 *
 * THIS PROJECTION IS LOSSY BY DESIGN. Markus's directive vocabulary
 * (card-grid, two-up, callout, tabs, timeline, ...) is a strict superset of
 * what Pretext can lay out -- Pretext cannot render a card grid. The
 * non-negotiable degradation rule (decided on PPY-92f846 / PPY-a10206):
 *
 *   Any directive Pretext cannot express recurses into its children so its
 *   content is preserved INLINE in `body`. Nothing is ever silently
 *   dropped.
 *
 * The two directives Pretext *can* express get pulled into their own
 * side-channels instead of `body`:
 *   - `pull-quote`  -> `pullQuotes[]`
 *   - `figure`      -> `images[]` (as `ArticleImageAsset`)
 *
 * This mirrors the verified prototype recorded on PPY-a10206: walk
 * `children` in order; paragraph/heading push their flattened text onto
 * `body`; `pull-quote` pushes onto `pullQuotes`; any other directive
 * recurses into its children. This module generalizes that same rule to
 * the rest of the typed block vocabulary (list/blockquote/code/table/
 * thematic_break/html) that the prototype's sample article didn't happen
 * to exercise, and to leaf directives with no children (`metric`, `video`)
 * by degrading to their textual attributes rather than dropping them.
 */

import type { ArticleImageAsset } from "./articles";
import {
  parseMarkusDocument,
  type MarkusBlock,
  type MarkusDirective,
  type MarkusDocument,
  type MarkusInline,
  type MarkusNode,
} from "./markus-ir";

export type PretextProjection = {
  body: string[];
  pullQuotes: string[];
  images: ArticleImageAsset[];
};

/** Flatten an inline node tree to plain text. No markup survives -- Pretext's
 * `body` is plain-text paragraphs, so emphasis/strong/links/code spans all
 * degrade to their text content. Images are dropped here (they are not
 * textual); a top-level `image` inline node inside a paragraph is rare in
 * practice and, if it occurs, its alt text is preserved instead of the
 * image itself, so no content vanishes silently. */
function inlineText(nodes: MarkusInline[]): string {
  return nodes
    .map((node): string => {
      switch (node.type) {
        case "text":
          return node.text;
        case "code_span":
          return node.code;
        case "emphasis":
        case "strong":
        case "strikethrough":
          return inlineText(node.children);
        case "link":
          return inlineText(node.children);
        case "image":
          return node.alt ?? "";
        case "soft_break":
          return " ";
        case "hard_break":
          return "\n";
        case "html_inline":
          // --allow-html is off for real Papyrus builds (see module doc);
          // preserve the raw text rather than silently dropping it in the
          // defensive case this ever appears.
          return node.value;
        default:
          return "";
      }
    })
    .join("")
    .trim();
}

/** Flatten a block node's own text content (not directives -- callers walk
 * directives separately so their degradation/side-channel rules apply). */
function blockText(block: MarkusBlock): string[] {
  switch (block.type) {
    case "heading":
    case "paragraph":
      return [inlineText(block.inline)];
    case "list":
      return block.items.map((item) => flattenBlocksToText(item.children).join(" "));
    case "blockquote":
      return flattenBlocksToText(block.children);
    case "code":
      // A code block has no inline richness; preserve its literal text
      // wholesale rather than dropping it because Pretext has no code
      // rendering of its own.
      return block.value.trim().length > 0 ? [block.value] : [];
    case "thematic_break":
      // No textual content exists to preserve; there is nothing to drop.
      return [];
    case "html":
      // See `inlineText`'s html_inline case: only reachable if IR was ever
      // produced with --allow-html, which Papyrus's build does not do.
      return block.value.trim().length > 0 ? [block.value] : [];
    case "table": {
      const rowText = (row: MarkusInline[][]) => row.map((cell) => inlineText(cell)).join(" | ");
      const lines = [rowText(block.header), ...block.rows.map(rowText)];
      return lines.filter((line) => line.trim().length > 0);
    }
    default:
      return [];
  }
}

function isDirective(node: MarkusNode): node is MarkusDirective {
  return node.type === "directive";
}

/** Degrade a leaf directive (no children by definition) to its textual
 * attributes, so `metric`/`video` don't vanish just because they have
 * nothing to recurse into. */
function leafDirectiveText(directive: MarkusDirective): string[] {
  const attrs = directive.attributes;
  if (directive.name === "metric") {
    const label = attrs.label != null ? String(attrs.label) : null;
    const value = attrs.value != null ? String(attrs.value) : null;
    const unit = attrs.unit != null ? String(attrs.unit) : "";
    const text = [label, value != null ? `${value}${unit}` : null].filter(Boolean).join(": ");
    return text.length > 0 ? [text] : [];
  }
  if (directive.name === "video") {
    const title = attrs.title != null ? String(attrs.title) : null;
    return title ? [title] : [];
  }
  // Unknown future leaf directive: fall back to whatever string-ish
  // attributes it has rather than dropping it silently.
  const text = Object.values(attrs)
    .filter((value) => typeof value === "string" && value.trim().length > 0)
    .join(" ");
  return text ? [text] : [];
}

/** Extract an ArticleImageAsset from a `figure` directive's attributes. */
function figureToImageAsset(directive: MarkusDirective, index: number): ArticleImageAsset {
  const attrs = directive.attributes;
  const src = attrs.src != null ? String(attrs.src) : "";
  const alt = attrs.alt != null ? String(attrs.alt) : "";
  const caption = attrs.caption != null ? String(attrs.caption) : undefined;
  const credit = attrs.credit != null ? String(attrs.credit) : "";
  return {
    id: `figure-${index}`,
    type: "image",
    src,
    alt,
    caption,
    credit,
  };
}

function flattenBlocksToText(nodes: MarkusNode[]): string[] {
  const out: string[] = [];
  for (const node of nodes) {
    if (isDirective(node)) {
      out.push(...directiveDegradedText(node));
    } else {
      out.push(...blockText(node));
    }
  }
  return out.filter((line) => line.trim().length > 0);
}

/** The degradation rule for a directive Pretext cannot render as itself:
 * recurse into its children (or, for a leaf directive with no children,
 * degrade to its attributes) so nothing is silently dropped. */
function directiveDegradedText(directive: MarkusDirective): string[] {
  if (directive.leaf || directive.children.length === 0) {
    return leafDirectiveText(directive);
  }
  return flattenBlocksToText(directive.children);
}

/**
 * Project a typed Markus document IR into the flat shape Pretext consumes.
 * Walks `document.children` in order:
 *   - `paragraph` / `heading` -> pushed onto `body`
 *   - `list` / `blockquote` / `code` / `table` / `thematic_break` / `html`
 *     -> degrade-preserved onto `body` (see `blockText`)
 *   - directive `pull-quote` -> its flattened text goes to `pullQuotes`,
 *     NOT `body`
 *   - directive `figure` -> becomes an `ArticleImageAsset` in `images`,
 *     NOT `body`
 *   - any other directive (`card-grid`, `card`, `two-up`, `column`,
 *     `callout`, `aside`, `details`, `tabs`, `tab`, `step-list`, `step`,
 *     `timeline`, `timeline-event`, and any future addition to the
 *     vocabulary) -> recurses into its children per the degradation rule
 */
export function projectMarkusDocumentToPretext(document: MarkusDocument): PretextProjection {
  const body: string[] = [];
  const pullQuotes: string[] = [];
  const images: ArticleImageAsset[] = [];
  let figureIndex = 0;

  for (const node of document.children) {
    if (isDirective(node)) {
      if (node.name === "pull-quote") {
        const text = flattenBlocksToText(node.children).join(" ");
        if (text.trim().length > 0) pullQuotes.push(text);
        continue;
      }
      if (node.name === "figure") {
        images.push(figureToImageAsset(node, figureIndex));
        figureIndex += 1;
        // A figure directive's own children (if any future Markus version
        // ever nests content under it) are still degraded into body so
        // nothing is dropped, matching the non-negotiable rule.
        if (node.children.length > 0) body.push(...flattenBlocksToText(node.children));
        continue;
      }
      body.push(...directiveDegradedText(node));
      continue;
    }
    body.push(...blockText(node));
  }

  return {
    body: body.filter((line) => line.trim().length > 0),
    pullQuotes,
    images,
  };
}

/**
 * Convenience entry point: parse + validate raw `markus ast` JSON (failing
 * loudly on schema mismatch, per `parseMarkusDocument`) and project it in
 * one call.
 */
export function projectMarkusJsonToPretext(raw: unknown): PretextProjection {
  return projectMarkusDocumentToPretext(parseMarkusDocument(raw));
}
