import { useMemo, type ReactNode } from "react";

/** Renders Markdown as React elements (headings, lists, tables, code, links), never as HTML, so stored text cannot inject markup.
 *  Links open in a new tab and only http(s) and mailto destinations become links. */
export function MarkdownContext({ className, text }: { className?: string; text: string }) {
  const blocks = useMemo(() => parseMarkdownBlocks(normalizeMarkdownForRendering(text)), [text]);
  return (
    <div className={className ? `news-desk-markdown-context ${className}` : "news-desk-markdown-context"}>
      {blocks.map((block, index) => renderMarkdownBlock(block, index))}
    </div>
  );
}

type MarkdownBlock =
  | { type: "code"; text: string }
  | { type: "heading"; depth: number; text: string }
  | { type: "list"; items: string[]; ordered: boolean }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "paragraph"; text: string };

function normalizeMarkdownForRendering(text: string): string {
  const trimmed = text.trim();
  const fencedMarkdown = /^```(?:markdown|md|mdx)?\s*\n([\s\S]*?)\n```$/i.exec(trimmed);
  const unwrapped = fencedMarkdown ? (fencedMarkdown[1] ?? "") : text;
  return normalizeMultilineMarkdownLinks(unwrapped);
}

function parseMarkdownBlocks(text: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = text.split(/\r?\n/);
  let paragraph: string[] = [];
  let list: string[] = [];
  let listOrdered = false;
  let code: string[] = [];
  let inCode = false;
  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", text: paragraph.join(" ").trim() });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list.length) {
      blocks.push({ type: "list", items: list, ordered: listOrdered });
      list = [];
      listOrdered = false;
    }
  };
  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex];
    if (line.trim().startsWith("```")) {
      if (inCode) {
        blocks.push({ type: "code", text: code.join("\n") });
        code = [];
        inCode = false;
      } else {
        flushParagraph();
        flushList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      code.push(line);
      continue;
    }
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }
    if (
      lineIndex + 1 < lines.length
      && looksLikeMarkdownTableHeaderLine(line)
      && isMarkdownTableDividerLine(lines[lineIndex + 1] ?? "")
    ) {
      flushParagraph();
      flushList();
      const headerCells = splitMarkdownTableCells(line);
      const dividerCells = splitMarkdownTableCells(lines[lineIndex + 1] ?? "");
      const columnCount = Math.max(headerCells.length, dividerCells.length, 1);
      const headers = normalizeMarkdownTableCells(headerCells, columnCount);
      const rows: string[][] = [];
      lineIndex += 2;
      while (lineIndex < lines.length) {
        const rowLine = lines[lineIndex] ?? "";
        if (!looksLikeMarkdownTableRowLine(rowLine)) {
          lineIndex -= 1;
          break;
        }
        rows.push(normalizeMarkdownTableCells(splitMarkdownTableCells(rowLine), columnCount));
        lineIndex += 1;
      }
      if (lineIndex >= lines.length) lineIndex -= 1;
      blocks.push({ type: "table", headers, rows });
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", depth: heading[1].length, text: heading[2].trim() });
      continue;
    }
    const bullet = /^(?:([-*+])\s+|(\d+)[.)]\s+)(.+)$/.exec(trimmed);
    if (bullet) {
      flushParagraph();
      const ordered = Boolean(bullet[2]);
      if (list.length && listOrdered !== ordered) flushList();
      listOrdered = ordered;
      list.push((bullet[3] ?? "").trim());
      continue;
    }
    flushList();
    paragraph.push(trimmed);
  }
  flushParagraph();
  flushList();
  if (code.length) blocks.push({ type: "code", text: code.join("\n") });
  return blocks;
}

function renderMarkdownBlock(block: MarkdownBlock, index: number): ReactNode {
  const key = `${block.type}-${index}`;
  if (block.type === "code") return <pre className="news-desk-analysis-command" key={key}>{block.text}</pre>;
  if (block.type === "list") {
    const ListTag = block.ordered ? "ol" : "ul";
    return (
      <ListTag key={key}>
        {block.items.map((item, itemIndex) => <li key={`${key}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>)}
      </ListTag>
    );
  }
  if (block.type === "heading") {
    if (block.depth <= 1) return <h3 key={key}>{block.text}</h3>;
    if (block.depth === 2) return <h4 key={key}>{block.text}</h4>;
    return <h5 key={key}>{block.text}</h5>;
  }
  if (block.type === "table") {
    return (
      <table key={key}>
        <thead>
          <tr>
            {block.headers.map((header, headerIndex) => (
              <th key={`${key}-head-${headerIndex}`} scope="col">{renderInlineMarkdown(header)}</th>
            ))}
          </tr>
        </thead>
        {block.rows.length ? (
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={`${key}-row-${rowIndex}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${key}-row-${rowIndex}-cell-${cellIndex}`}>{renderInlineMarkdown(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        ) : null}
      </table>
    );
  }
  return <p key={key}>{renderInlineMarkdown(block.text)}</p>;
}

function renderInlineMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let index = 0;
  let plain = "";
  const flushPlain = () => {
    if (!plain) return;
    nodes.push(plain);
    plain = "";
  };

  while (index < text.length) {
    const linkLike = parseMarkdownLinkLikeAt(text, index);
    if (linkLike) {
      flushPlain();
      if (!linkLike.image) {
        const href = normalizeInlineMarkdownHref(linkLike.hrefRaw);
        const label = collapseMarkdownLinkLabel(linkLike.label);
        if (href) {
          nodes.push(
            <a href={href} key={`${index}-link`} rel="noopener noreferrer" target="_blank">
              {renderInlineMarkdown(label)}
            </a>,
          );
        } else {
          nodes.push(linkLike.raw);
        }
      }
      index += linkLike.length;
      continue;
    }

    if (text.startsWith("**", index) || text.startsWith("__", index)) {
      const marker = text.slice(index, index + 2);
      const end = text.indexOf(marker, index + 2);
      if (end > index + 2) {
        flushPlain();
        nodes.push(<strong key={`${index}-strong`}>{renderInlineMarkdown(text.slice(index + 2, end))}</strong>);
        index = end + 2;
        continue;
      }
    }

    if (text.startsWith("~~", index)) {
      const end = text.indexOf("~~", index + 2);
      if (end > index + 2) {
        flushPlain();
        nodes.push(<del key={`${index}-strike`}>{renderInlineMarkdown(text.slice(index + 2, end))}</del>);
        index = end + 2;
        continue;
      }
    }

    if (text[index] === "*" || text[index] === "_") {
      const marker = text[index];
      const end = text.indexOf(marker, index + 1);
      if (end > index + 1) {
        flushPlain();
        nodes.push(<em key={`${index}-em`}>{renderInlineMarkdown(text.slice(index + 1, end))}</em>);
        index = end + 1;
        continue;
      }
    }

    if (text[index] === "`") {
      const end = text.indexOf("`", index + 1);
      if (end > index + 1) {
        flushPlain();
        nodes.push(<code key={`${index}-code`}>{text.slice(index + 1, end)}</code>);
        index = end + 1;
        continue;
      }
    }

    const autolinkMatch = /^(<https?:\/\/[^>\s]+>|https?:\/\/[^\s<]+)/.exec(text.slice(index));
    if (autolinkMatch) {
      flushPlain();
      const token = autolinkMatch[1];
      const href = normalizeInlineMarkdownHref(token);
      if (href) {
        nodes.push(
          <a href={href} key={`${index}-autolink`} rel="noopener noreferrer" target="_blank">
            {href}
          </a>,
        );
      } else {
        nodes.push(token);
      }
      index += token.length;
      continue;
    }

    plain += text[index];
    index += 1;
  }

  flushPlain();
  return nodes;
}

function normalizeInlineMarkdownHref(rawHref: string): string | null {
  const href = extractMarkdownHrefDestination(rawHref);
  if (!href) return null;
  if (/^(https?:\/\/|mailto:)/i.test(href)) return href;
  return null;
}

function normalizeMultilineMarkdownLinks(text: string): string {
  let normalized = "";
  let index = 0;
  while (index < text.length) {
    const linkLike = parseMarkdownLinkLikeAt(text, index);
    if (!linkLike || linkLike.image || !linkLike.raw.includes("\n")) {
      normalized += text[index];
      index += 1;
      continue;
    }
    const href = extractMarkdownHrefDestination(linkLike.hrefRaw);
    const label = collapseMarkdownLinkLabel(linkLike.label);
    if (!href || !label) {
      normalized += linkLike.raw;
      index += linkLike.length;
      continue;
    }
    normalized += `[${label}](${href})`;
    index += linkLike.length;
  }
  return normalized;
}

function collapseMarkdownLinkLabel(label: string): string {
  const withoutImages = label.replace(/!\[[^\]]*\]\((?:[^)(]|\([^)(]*\))*\)/g, " ");
  return withoutImages
    .replace(/\r?\n+/g, " ")
    .replace(/(^|\s)#{1,6}\s+/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function extractMarkdownHrefDestination(rawHref: string): string {
  const trimmed = rawHref.trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("<")) {
    const closing = trimmed.indexOf(">");
    if (closing > 1) return trimmed.slice(1, closing).trim();
  }
  const match = /^(\S+)/.exec(trimmed);
  return match?.[1]?.trim() ?? "";
}

function parseMarkdownLinkLikeAt(
  source: string,
  startIndex: number,
): { hrefRaw: string; image: boolean; label: string; length: number; raw: string } | null {
  const image = source.startsWith("![", startIndex);
  const link = source[startIndex] === "[";
  if (!image && !link) return null;
  const labelStart = startIndex + (image ? 2 : 1);
  const labelEnd = findMatchingBracketIndex(source, labelStart, "[", "]");
  if (labelEnd < 0) return null;
  let next = labelEnd + 1;
  while (next < source.length && /\s/.test(source[next])) next += 1;
  if (source[next] !== "(") return null;
  const hrefStart = next + 1;
  const hrefEnd = findMatchingBracketIndex(source, hrefStart, "(", ")");
  if (hrefEnd < 0) return null;
  const raw = source.slice(startIndex, hrefEnd + 1);
  return {
    image,
    label: source.slice(labelStart, labelEnd),
    hrefRaw: source.slice(hrefStart, hrefEnd),
    length: raw.length,
    raw,
  };
}

function findMatchingBracketIndex(source: string, contentStart: number, open: string, close: string): number {
  let depth = 1;
  for (let index = contentStart; index < source.length; index += 1) {
    const ch = source[index];
    if (ch === "\\") {
      index += 1;
      continue;
    }
    if (ch === open) {
      depth += 1;
      continue;
    }
    if (ch !== close) continue;
    depth -= 1;
    if (depth === 0) return index;
  }
  return -1;
}

function looksLikeMarkdownTableHeaderLine(line: string): boolean {
  return /\|/.test(line.trim());
}

function looksLikeMarkdownTableRowLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return false;
  if (!/\|/.test(trimmed)) return false;
  if (isMarkdownTableDividerLine(trimmed)) return false;
  return true;
}

function isMarkdownTableDividerLine(line: string): boolean {
  const cells = splitMarkdownTableCells(line);
  if (!cells.length) return false;
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function splitMarkdownTableCells(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  if (!trimmed) return [];
  const cells: string[] = [];
  let current = "";
  let escaping = false;
  for (let index = 0; index < trimmed.length; index += 1) {
    const ch = trimmed[index];
    if (escaping) {
      current += ch;
      escaping = false;
      continue;
    }
    if (ch === "\\") {
      escaping = true;
      current += ch;
      continue;
    }
    if (ch === "|") {
      cells.push(current.trim());
      current = "";
      continue;
    }
    current += ch;
  }
  cells.push(current.trim());
  return cells;
}

function normalizeMarkdownTableCells(cells: string[], columnCount: number): string[] {
  const normalized = cells.slice(0, columnCount);
  while (normalized.length < columnCount) normalized.push("");
  return normalized;
}
