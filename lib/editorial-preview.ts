/**
 * Places Humanus findings on the rendered Markus preview.
 *
 * Humanus reports spans in the markup; the preview renders an IR tree with no
 * character offsets. Both sides agree on the words a reader sees, so findings
 * are placed by text: each Humanus paragraph is matched, in document order, to
 * the rendered prose block with the same words, and each finding's plain
 * excerpt is located inside that block. Whitespace is ignored while matching,
 * because rendering and Humanus collapse it differently (citations, breaks).
 *
 * "Rendered text" is defined by `inlineLeaves`, which the preview renderer also
 * uses, so offsets computed here are offsets the renderer can split on.
 */
import type { EditorialCheckResult, EditorialFinding, Severity, Span } from "./editorial-checks";
import type { MarkusBlock, MarkusDocument, MarkusInline, MarkusNode } from "./markus-ir";

export const CITATION_TOKEN = /PAPYRUSMARKUP\d{5}END/g;

export type InlineLeaf =
  | { kind: "text"; node: MarkusInline & { type: "text" }; start: number; pieces: { raw: string; start: number; isToken: boolean }[] }
  | { kind: "code"; node: MarkusInline & { type: "code_span" }; start: number; text: string }
  | { kind: "break"; start: number; text: string }
  | { kind: "opaque"; start: number };

/** The reader-visible text of a run of inlines; citation tokens and images take no width. */
export function inlineLeaves(inlines: MarkusInline[], offset = 0): { leaves: InlineLeaf[]; text: string } {
  const leaves: InlineLeaf[] = [];
  let text = "";
  const walk = (nodes: MarkusInline[]) => {
    for (const node of nodes) {
      const start = offset + text.length;
      switch (node.type) {
        case "text": {
          const pieces: { raw: string; start: number; isToken: boolean }[] = [];
          let cursor = 0;
          let plainLength = 0;
          for (const match of node.text.matchAll(CITATION_TOKEN)) {
            const index = match.index ?? 0;
            if (index > cursor) {
              pieces.push({ raw: node.text.slice(cursor, index), start: start + plainLength, isToken: false });
              plainLength += index - cursor;
            }
            pieces.push({ raw: match[0], start: start + plainLength, isToken: true });
            cursor = index + match[0].length;
          }
          if (cursor < node.text.length) {
            pieces.push({ raw: node.text.slice(cursor), start: start + plainLength, isToken: false });
            plainLength += node.text.length - cursor;
          }
          leaves.push({ kind: "text", node, start, pieces });
          text += pieces.filter((piece) => !piece.isToken).map((piece) => piece.raw).join("");
          break;
        }
        case "code_span":
          leaves.push({ kind: "code", node, start, text: node.code });
          text += node.code;
          break;
        case "soft_break":
        case "hard_break":
          leaves.push({ kind: "break", start, text: " " });
          text += " ";
          break;
        case "emphasis":
        case "strong":
        case "strikethrough":
        case "link":
          walk(node.children);
          break;
        default:
          leaves.push({ kind: "opaque", start });
      }
    }
  };
  walk(inlines);
  return { leaves, text };
}

/** Prose blocks (paragraphs and headings, including those inside lists, quotes and directives) in reading order. */
export function proseBlocks(document: MarkusDocument): (MarkusBlock & { inline: MarkusInline[] })[] {
  const blocks: (MarkusBlock & { inline: MarkusInline[] })[] = [];
  const visit = (nodes: MarkusNode[]) => {
    for (const node of nodes) {
      if (node.type === "directive") visit(node.children);
      else if (node.type === "paragraph" || node.type === "heading") blocks.push(node);
      else if (node.type === "list") for (const item of node.items) visit(item.children);
      else if (node.type === "blockquote") visit(node.children);
    }
  };
  visit(document.children);
  return blocks;
}

export type PreviewMark = Span & { findingIds: string[]; severity: Severity; status: EditorialFinding["status"] };
export type PreviewSentence = Span & { segmentId: string; source: Span };

/** What the preview needs for one rendered block, in that block's rendered-text offsets. */
export type BlockAnnotation = { marks: PreviewMark[]; sentences: PreviewSentence[] };

export type PreviewPlan = WeakMap<object, BlockAnnotation>;

const SEVERITY_RANK: Record<Severity, number> = { error: 0, warn: 1, info: 2 };

/** Text without whitespace, with a map from each kept character back to its index in the original. */
function compact(text: string): { value: string; index: number[] } {
  let value = "";
  const index: number[] = [];
  for (let i = 0; i < text.length; i += 1) {
    if (!/\s/.test(text[i])) {
      value += text[i];
      index.push(i);
    }
  }
  return { value, index };
}

/** Locate `needle` in `haystack` ignoring whitespace; the occurrence nearest `near` (a 0..1 position) wins. */
export function locate(haystack: string, needle: string, near = 0): Span | null {
  const hay = compact(haystack);
  const want = compact(needle).value;
  if (!want) return null;
  let best: number | null = null;
  for (let at = hay.value.indexOf(want); at !== -1; at = hay.value.indexOf(want, at + 1)) {
    if (best === null || Math.abs(at / Math.max(hay.value.length, 1) - near) < Math.abs(best / Math.max(hay.value.length, 1) - near)) best = at;
  }
  if (best === null) return null;
  return { start: hay.index[best], end: hay.index[best + want.length - 1] + 1 };
}

/** The identity of a block's words: no whitespace, no stray emphasis or code markers. */
function blockKey(text: string): string {
  return compact(text).value.replace(/[*_`~]/g, "");
}

/** Match every Humanus paragraph to a rendered block and place its findings and sentences there. */
export function planPreview(
  document: MarkusDocument,
  result: EditorialCheckResult,
  findings: EditorialFinding[],
): PreviewPlan {
  const plan: PreviewPlan = new WeakMap();
  const blocks = proseBlocks(document).map((block) => ({ block, text: inlineLeaves(block.inline).text }));
  const paragraphs = result.segments.filter((segment) => segment.kind === "paragraph" && segment.text);
  let cursor = 0;
  for (const paragraph of paragraphs) {
    const wanted = blockKey(paragraph.text ?? "");
    let matched = -1;
    for (let candidate = cursor; candidate < blocks.length; candidate += 1) {
      if (blockKey(blocks[candidate].text) === wanted) {
        matched = candidate;
        break;
      }
    }
    if (matched === -1) continue;
    cursor = matched + 1;
    const { block, text } = blocks[matched];
    const sentences: PreviewSentence[] = [];
    for (const sentence of result.segments.filter((s) => s.kind === "sentence" && s.parentId === paragraph.id)) {
      const near = (sentence.start - paragraph.start) / Math.max(paragraph.end - paragraph.start, 1);
      const span = locate(text, sentence.text ?? "", near);
      if (span) sentences.push({ ...span, segmentId: sentence.id, source: { start: sentence.start, end: sentence.end } });
    }
    const ranges: (Span & { finding: EditorialFinding })[] = [];
    for (const finding of findings) {
      const inParagraph =
        finding.segmentId === paragraph.id ||
        result.segments.some((s) => s.id === finding.segmentId && s.parentId === paragraph.id);
      if (!inParagraph || !finding.excerptText) continue;
      const near = (finding.span.start - paragraph.start) / Math.max(paragraph.end - paragraph.start, 1);
      const span = locate(text, finding.excerptText, near);
      if (span) ranges.push({ ...span, finding });
    }
    plan.set(block, { marks: flatten(ranges), sentences });
  }
  return plan;
}

/** Overlapping finding ranges become non-overlapping marks, each listing every finding it belongs to. */
function flatten(ranges: (Span & { finding: EditorialFinding })[]): PreviewMark[] {
  const cuts = [...new Set(ranges.flatMap((range) => [range.start, range.end]))].sort((a, b) => a - b);
  const marks: PreviewMark[] = [];
  for (let i = 0; i < cuts.length - 1; i += 1) {
    const start = cuts[i];
    const end = cuts[i + 1];
    const covering = ranges.filter((range) => range.start <= start && end <= range.end).map((range) => range.finding);
    if (covering.length === 0) continue;
    const strongest = [...covering].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])[0];
    const previous = marks[marks.length - 1];
    const ids = covering.map((finding) => finding.id).sort();
    if (previous && previous.end === start && previous.findingIds.join() === ids.join()) {
      previous.end = end;
      continue;
    }
    marks.push({
      start,
      end,
      findingIds: ids,
      severity: strongest.severity,
      status: covering.every((finding) => finding.status === "review") ? "review" : "violation",
    });
  }
  return marks;
}

/** A selection on the preview, as the source span of the whole sentences it touches. */
export function selectionToSource(annotation: BlockAnnotation | undefined, selection: Span): Span | null {
  if (!annotation) return null;
  const touched = annotation.sentences.filter((sentence) => sentence.start < selection.end && selection.start < sentence.end);
  if (touched.length === 0) return null;
  return {
    start: Math.min(...touched.map((sentence) => sentence.source.start)),
    end: Math.max(...touched.map((sentence) => sentence.source.end)),
  };
}

/** Split [start, end) of rendered text at mark boundaries; each piece says which mark (if any) covers it. */
export function splitByMarks(start: number, end: number, marks: PreviewMark[]): { start: number; end: number; mark: PreviewMark | null }[] {
  const pieces: { start: number; end: number; mark: PreviewMark | null }[] = [];
  let cursor = start;
  for (const mark of marks) {
    if (mark.end <= cursor || mark.start >= end) continue;
    if (mark.start > cursor) pieces.push({ start: cursor, end: mark.start, mark: null });
    const pieceEnd = Math.min(mark.end, end);
    pieces.push({ start: Math.max(mark.start, cursor), end: pieceEnd, mark });
    cursor = pieceEnd;
  }
  if (cursor < end) pieces.push({ start: cursor, end, mark: null });
  return pieces;
}
