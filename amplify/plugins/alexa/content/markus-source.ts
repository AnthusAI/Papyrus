/**
 * A reader for the Markus source of a published story (the body of the `.md` twin), producing the same `MarkusDocument` nodes the
 * stored `bodyIr` has (lib/markus-ir.ts). Papyrus parses Markus in Python; the skill function has no Python and the public
 * projection carries the source only, so this reads the subset a story uses: headings, paragraphs, lists, block quotes, code, rules,
 * tables, container (`:::name{attrs}` ... `:::`) and leaf (`::name{attrs}`) directives, and the common inline marks.
 * It never throws on odd input: what it does not understand reads as a paragraph.
 */
import type {
  MarkusBlock,
  MarkusDirective,
  MarkusDirectiveAttributes,
  MarkusDocument,
  MarkusInline,
  MarkusListItem,
  MarkusNode,
} from "../../../../lib/markus-ir";
import { MARKUS_IR_SCHEMA_VERSION } from "../../../../lib/markus-ir";

const FENCE = /^(`{3,}|~{3,})\s*([^\s`]*)/;
const CONTAINER_OPEN = /^(:{3,})([A-Za-z][\w-]*)(\{.*\})?\s*$/;
const CONTAINER_CLOSE = /^:{3,}\s*$/;
const LEAF = /^::([A-Za-z][\w-]*)(\{.*\})?\s*$/;
const HEADING = /^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/;
const THEMATIC_BREAK = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/;
const LIST_ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const TABLE_DELIMITER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

function attributesOf(raw: string | undefined): MarkusDirectiveAttributes {
  const attributes: MarkusDirectiveAttributes = {};
  if (!raw) return attributes;
  for (const match of raw.slice(1, -1).matchAll(/([\w-]+)=(?:"([^"]*)"|([^\s}"]+))/g)) {
    const value = match[2] ?? match[3];
    attributes[match[1]] = /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value === "true" ? true : value === "false" ? false : value;
  }
  return attributes;
}

function isBlockStart(line: string): boolean {
  return (
    FENCE.test(line) ||
    CONTAINER_OPEN.test(line) ||
    CONTAINER_CLOSE.test(line) ||
    LEAF.test(line) ||
    HEADING.test(line) ||
    THEMATIC_BREAK.test(line) ||
    line.startsWith(">") ||
    LIST_ITEM.test(line)
  );
}

// ---------------------------------------------------------------- inlines

function matchingBracket(text: string, open: number, left: string, right: string): number {
  let depth = 0;
  for (let index = open; index < text.length; index += 1) {
    if (text[index] === "\\") index += 1;
    else if (text[index] === left) depth += 1;
    else if (text[index] === right) {
      depth -= 1;
      if (depth === 0) return index;
    }
  }
  return -1;
}

function linkAt(text: string, start: number): { label: string; target: string; end: number } | undefined {
  const closeLabel = matchingBracket(text, start, "[", "]");
  if (closeLabel < 0 || text[closeLabel + 1] !== "(") return undefined;
  const closeTarget = matchingBracket(text, closeLabel + 1, "(", ")");
  if (closeTarget < 0) return undefined;
  return { label: text.slice(start + 1, closeLabel), target: text.slice(closeLabel + 2, closeTarget).trim(), end: closeTarget + 1 };
}

export function parseInline(text: string): MarkusInline[] {
  const out: MarkusInline[] = [];
  let buffer = "";
  const flush = () => {
    if (buffer) out.push({ type: "text", text: buffer });
    buffer = "";
  };
  let index = 0;
  while (index < text.length) {
    const char = text[index];
    const rest = text.slice(index);
    if (char === "\\" && index + 1 < text.length && /[\\`*_{}[\]()#+\-.!|~>:]/.test(text[index + 1])) {
      buffer += text[index + 1];
      index += 2;
      continue;
    }
    if (char === "`") {
      const run = /^`+/.exec(rest)![0];
      const close = text.indexOf(run, index + run.length);
      if (close > 0) {
        flush();
        out.push({ type: "code_span", code: text.slice(index + run.length, close).trim() });
        index = close + run.length;
        continue;
      }
    }
    if (rest.startsWith("![")) {
      const link = linkAt(text, index + 1);
      if (link) {
        flush();
        out.push({ type: "image", src: link.target.split(/\s+/)[0] || null, alt: link.label, title: null });
        index = link.end;
        continue;
      }
    }
    if (char === "[") {
      const link = linkAt(text, index);
      if (link) {
        flush();
        out.push({ type: "link", href: link.target.split(/\s+/)[0] || null, title: null, children: parseInline(link.label) });
        index = link.end;
        continue;
      }
    }
    const marker = rest.startsWith("**") ? "**" : rest.startsWith("__") ? "__" : rest.startsWith("~~") ? "~~" : undefined;
    if (marker) {
      const close = text.indexOf(marker, index + 2);
      if (close > index + 2) {
        flush();
        const children = parseInline(text.slice(index + 2, close));
        out.push(marker === "~~" ? { type: "strikethrough", children } : { type: "strong", children });
        index = close + 2;
        continue;
      }
    }
    if ((char === "*" || char === "_") && text[index + 1] !== " " && text[index + 1] !== undefined) {
      const intraword = char === "_" && /\w/.test(text[index - 1] ?? "");
      const close = intraword ? -1 : text.indexOf(char, index + 1);
      if (close > index + 1 && (char === "*" || !/\w/.test(text[close + 1] ?? ""))) {
        flush();
        out.push({ type: "emphasis", children: parseInline(text.slice(index + 1, close)) });
        index = close + 1;
        continue;
      }
    }
    buffer += char;
    index += 1;
  }
  flush();
  return out;
}

function inlinesWithBreaks(lines: readonly string[]): MarkusInline[] {
  const out: MarkusInline[] = [];
  lines.forEach((line, position) => {
    if (position > 0) out.push({ type: "soft_break" });
    out.push(...parseInline(line.trim()));
  });
  return out;
}

// ----------------------------------------------------------------- blocks

function tableCells(line: string): string[] {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function parseBlocks(lines: readonly string[]): MarkusNode[] {
  const nodes: MarkusNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const number = index + 1;
    if (line.trim() === "") {
      index += 1;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence) {
      const value: string[] = [];
      index += 1;
      while (index < lines.length && !(lines[index].startsWith(fence[1][0].repeat(fence[1].length)) && lines[index].trim().replace(/[`~]/g, "") === "")) {
        value.push(lines[index]);
        index += 1;
      }
      index += 1;
      nodes.push({ type: "code", lang: fence[2] || null, value: value.join("\n"), line: number });
      continue;
    }

    const container = CONTAINER_OPEN.exec(line);
    if (container) {
      let depth = 1;
      let close = index + 1;
      for (; close < lines.length; close += 1) {
        if (CONTAINER_OPEN.test(lines[close])) depth += 1;
        else if (CONTAINER_CLOSE.test(lines[close])) {
          depth -= 1;
          if (depth === 0) break;
        }
      }
      const directive: MarkusDirective = {
        type: "directive",
        name: container[2],
        attributes: attributesOf(container[3]),
        leaf: false,
        line: number,
        children: parseBlocks(lines.slice(index + 1, close)),
      };
      nodes.push(directive);
      index = close + 1;
      continue;
    }
    if (CONTAINER_CLOSE.test(line)) {
      index += 1; // a stray closing fence
      continue;
    }
    const leaf = LEAF.exec(line);
    if (leaf) {
      nodes.push({ type: "directive", name: leaf[1], attributes: attributesOf(leaf[2]), leaf: true, line: number, children: [] });
      index += 1;
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      nodes.push({ type: "heading", level: heading[1].length, inline: parseInline(heading[2]), line: number });
      index += 1;
      continue;
    }
    if (THEMATIC_BREAK.test(line)) {
      nodes.push({ type: "thematic_break", line: number });
      index += 1;
      continue;
    }

    if (line.startsWith(">")) {
      const quoted: string[] = [];
      while (index < lines.length && lines[index].startsWith(">")) {
        quoted.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      nodes.push({ type: "blockquote", children: parseBlocks(quoted).filter((node): node is MarkusBlock => node.type !== "directive"), line: number });
      continue;
    }

    const firstItem = LIST_ITEM.exec(line);
    if (firstItem && firstItem[1].length < 4) {
      const ordered = /\d/.test(firstItem[2]);
      const items: MarkusListItem[] = [];
      const start = ordered ? Number.parseInt(firstItem[2], 10) : null;
      while (index < lines.length) {
        const item = LIST_ITEM.exec(lines[index]);
        if (!item || item[1].length >= 4 || /\d/.test(item[2]) !== ordered) break;
        const itemLine = index + 1;
        const content: string[] = [item[3]];
        index += 1;
        while (index < lines.length) {
          const next = lines[index];
          if (next.trim() === "") {
            const after = lines.slice(index).find((candidate) => candidate.trim() !== "");
            if (after !== undefined && /^\s{2,}\S/.test(after)) {
              content.push("");
              index += 1;
              continue;
            }
            break;
          }
          if (/^\s{2,}\S/.test(next)) {
            content.push(next.replace(/^\s{1,4}/, ""));
            index += 1;
          } else if (!isBlockStart(next) && !LIST_ITEM.test(next)) {
            content.push(next);
            index += 1;
          } else break;
        }
        const task = /^\[([ xX])\]\s+/.exec(content[0]);
        if (task) content[0] = content[0].slice(task[0].length);
        items.push({
          type: "list_item",
          checked: task ? task[1] !== " " : null,
          children: parseBlocks(content).filter((node): node is MarkusBlock => node.type !== "directive"),
          line: itemLine,
        });
      }
      nodes.push({ type: "list", ordered, start, items, line: number });
      continue;
    }

    if (line.includes("|") && index + 1 < lines.length && TABLE_DELIMITER.test(lines[index + 1]) && lines[index + 1].includes("-")) {
      const header = tableCells(line).map(parseInline);
      const rows: MarkusInline[][][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim() !== "" && lines[index].includes("|")) {
        rows.push(tableCells(lines[index]).map(parseInline));
        index += 1;
      }
      nodes.push({ type: "table", align: header.map(() => null), header, rows, line: number });
      continue;
    }

    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() !== "" && !isBlockStart(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    nodes.push({ type: "paragraph", inline: inlinesWithBreaks(paragraph), line: number });
  }
  return nodes;
}

export function parseMarkusSource(source: string): MarkusDocument {
  return {
    type: "document",
    schema_version: MARKUS_IR_SCHEMA_VERSION,
    front_matter: {},
    children: parseBlocks(source.replace(/\r\n?/g, "\n").split("\n")),
  };
}
