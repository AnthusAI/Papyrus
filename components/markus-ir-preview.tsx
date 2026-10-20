import type { MouseEvent as ReactMouseEvent, ReactNode } from "react";
import { CITATION_TOKEN, planPreview, selectionToSource, splitByMarks, type BlockAnnotation, type PreviewMark, type PreviewPlan } from "../lib/editorial-preview";
import type { EditorialCheckResult, EditorialFinding, Span } from "../lib/editorial-checks";
import {
  parseMarkusDocument,
  type MarkusBlock,
  type MarkusDirective,
  type MarkusInline,
  type MarkusNode,
} from "../lib/markus-ir";

const TOKEN_PATTERN = /PAPYRUSMARKUP\d{5}END/g;
const WHOLE_TOKEN_PATTERN = /^PAPYRUSMARKUP\d{5}END$/;

type PreviewSidecar = {
  images: Record<string, Record<string, unknown>>;
  citations: Record<string, string[]>;
  citationLists: Record<string, unknown>;
  bibliography: string[];
};

/** Editorial findings drawn on the preview (see lib/editorial-preview.ts). */
export type PreviewEditorial = {
  /** A check result computed for the same body the preview shows, and the findings to draw from it. */
  result: EditorialCheckResult;
  findings: EditorialFinding[];
  activeFindingIds?: readonly string[];
  /** A marked passage was clicked. */
  onOpenMark: (findingIds: string[], anchor: HTMLElement) => void;
  /** Text was selected inside one prose block: the source span of the sentences it touches. */
  onSelectSource?: (source: Span, anchor: DOMRect) => void;
};

type PreviewContext = {
  editorial?: PreviewEditorial & { plan: PreviewPlan; blocks: Map<string, BlockAnnotation> };
  sidecar: PreviewSidecar;
  citationNumbers: Map<string, number>;
  imageUrls: Record<string, string>;
  dynamicDirectives: Record<string, (attributes: Record<string, unknown>) => ReactNode>;
  renderLink?: (href: string, children: ReactNode) => ReactNode | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readSidecar(envelope: Record<string, unknown>): PreviewSidecar {
  const sidecar = envelope.papyrus;
  if (!isRecord(sidecar)) throw new Error("bodyIr.papyrus is missing");
  const { images, citations, citationLists, bibliography } = sidecar;
  if (!isRecord(images) || !isRecord(citations) || !isRecord(citationLists) || !Array.isArray(bibliography)) {
    throw new Error("bodyIr.papyrus must contain images, citations, citationLists and bibliography");
  }
  return {
    images: images as PreviewSidecar["images"],
    citations: citations as PreviewSidecar["citations"],
    citationLists,
    bibliography: bibliography.map(String),
  };
}

function numberCitationsByFirstAppearance(document: unknown, sidecar: PreviewSidecar): Map<string, number> {
  const numbers = new Map<string, number>();
  for (const token of JSON.stringify(document).match(TOKEN_PATTERN) ?? []) {
    for (const key of sidecar.citations[token] ?? []) {
      if (!numbers.has(key)) numbers.set(key, numbers.size + 1);
    }
  }
  return numbers;
}

function imagePlaceholder(token: string, context: PreviewContext): ReactNode {
  const entry = context.sidecar.images[token];
  const src = typeof entry?.src === "string" ? entry.src : "";
  const alt = typeof entry?.alt === "string" ? entry.alt : "";
  const url = context.imageUrls[src];
  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        alt={alt}
        className="my-3 h-auto max-w-full"
        data-markus-preview-image-loaded
        loading="lazy"
        src={url}
      />
    );
  }
  return (
    <div
      className="my-3 rounded-lg border border-dashed border-border bg-muted/30 px-3 py-6 text-center text-xs text-muted-foreground"
      data-markus-preview-image
    >
      {`Image: ${src} (${alt})`}
    </div>
  );
}

function renderText(text: string, context: PreviewContext): ReactNode {
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(TOKEN_PATTERN)) {
    const token = match[0];
    const index = match.index ?? 0;
    const keys = context.sidecar.citations[token];
    if (!keys) continue;
    if (index > cursor) parts.push(text.slice(cursor, index));
    parts.push(
      <sup className="text-primary" data-editorial-skip key={`${index}-${token}`}>
        {keys.map((key) => `[${context.citationNumbers.get(key)}]`).join("")}
      </sup>,
    );
    cursor = index + token.length;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}

function renderInlines(inlines: MarkusInline[], context: PreviewContext): ReactNode[] {
  return inlines.map((node, index) => {
    switch (node.type) {
      case "text":
        return <span key={index}>{renderText(node.text, context)}</span>;
      case "emphasis":
        return <em key={index}>{renderInlines(node.children, context)}</em>;
      case "strong":
        return <strong key={index}>{renderInlines(node.children, context)}</strong>;
      case "strikethrough":
        return <s key={index}>{renderInlines(node.children, context)}</s>;
      case "code_span":
        return <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]" key={index}>{node.code}</code>;
      case "link": {
        const custom = node.href ? context.renderLink?.(node.href, renderInlines(node.children, context)) : null;
        if (custom) return <span key={index}>{custom}</span>;
        return node.href ? (
          <a className="text-primary underline" href={node.href} key={index} rel="noopener noreferrer" target="_blank">
            {renderInlines(node.children, context)}
          </a>
        ) : (
          <span key={index}>{renderInlines(node.children, context)}</span>
        );
      }
      case "image":
        return (
          <span className="rounded border border-dashed border-border px-1 text-xs text-muted-foreground" data-editorial-skip key={index}>
            {`Image: ${node.src ?? ""} (${node.alt})`}
          </span>
        );
      case "soft_break":
        return <span key={index}>{" "}</span>;
      case "hard_break":
        return <br key={index} />;
      case "html_inline":
        return <code className="font-mono text-xs" key={index}>{node.value}</code>;
    }
  });
}

const MARK_CLASSES: Record<PreviewMark["severity"], string> = {
  error: "decoration-destructive",
  warn: "decoration-amber-500",
  info: "decoration-sky-500",
};

function markElement(text: string, mark: PreviewMark, key: string, context: PreviewContext): ReactNode {
  const active = mark.findingIds.some((id) => context.editorial?.activeFindingIds?.includes(id));
  return (
    <mark
      className={`cursor-pointer bg-transparent text-inherit underline underline-offset-4 ${mark.status === "review" ? "decoration-dotted" : "decoration-wavy"} ${MARK_CLASSES[mark.severity]} ${active ? "rounded-sm bg-ring/25" : ""}`}
      data-editorial-mark={mark.findingIds.join(" ")}
      key={key}
      onClick={(event) => {
        event.preventDefault();
        context.editorial?.onOpenMark(mark.findingIds, event.currentTarget);
      }}
    >
      {text}
    </mark>
  );
}

/** Like renderInlines, but splits rendered text at editorial marks (offsets as in inlineLeaves). */
function renderMarkedInlines(inlines: MarkusInline[], context: PreviewContext, marks: PreviewMark[], cursor: { at: number }): ReactNode[] {
  const marked = (text: string, keyPrefix: string): ReactNode[] => {
    const start = cursor.at;
    cursor.at += text.length;
    return splitByMarks(start, start + text.length, marks).map((piece, pieceIndex) => {
      const slice = text.slice(piece.start - start, piece.end - start);
      return piece.mark ? markElement(slice, piece.mark, `${keyPrefix}-${pieceIndex}`, context) : slice;
    });
  };
  return inlines.map((node, index) => {
    switch (node.type) {
      case "text": {
        const parts: ReactNode[] = [];
        let last = 0;
        for (const match of node.text.matchAll(CITATION_TOKEN)) {
          const at = match.index ?? 0;
          if (at > last) parts.push(...marked(node.text.slice(last, at), `${index}-${last}`));
          parts.push(<span key={`${index}-t${at}`}>{renderText(match[0], context)}</span>);
          last = at + match[0].length;
        }
        if (last < node.text.length) parts.push(...marked(node.text.slice(last), `${index}-${last}`));
        return <span key={index}>{parts}</span>;
      }
      case "emphasis":
        return <em key={index}>{renderMarkedInlines(node.children, context, marks, cursor)}</em>;
      case "strong":
        return <strong key={index}>{renderMarkedInlines(node.children, context, marks, cursor)}</strong>;
      case "strikethrough":
        return <s key={index}>{renderMarkedInlines(node.children, context, marks, cursor)}</s>;
      case "code_span":
        return <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]" key={index}>{marked(node.code, `${index}`)}</code>;
      case "link": {
        const children = renderMarkedInlines(node.children, context, marks, cursor);
        const custom = node.href ? context.renderLink?.(node.href, children) : null;
        if (custom) return <span key={index}>{custom}</span>;
        return node.href ? (
          <a className="text-primary underline" href={node.href} key={index} rel="noopener noreferrer" target="_blank">{children}</a>
        ) : (
          <span key={index}>{children}</span>
        );
      }
      case "soft_break":
        cursor.at += 1;
        return <span key={index}>{" "}</span>;
      case "hard_break":
        cursor.at += 1;
        return <br key={index} />;
      default:
        return renderInlines([node], context)[0];
    }
  });
}

/** Render a prose block's inlines, with editorial marks when the block has an annotation. */
function proseInlines(block: { inline: MarkusInline[] }, context: PreviewContext): { children: ReactNode[]; blockKey?: string } {
  const annotation = context.editorial?.plan.get(block);
  if (!context.editorial || !annotation) return { children: renderInlines(block.inline, context) };
  const blockKey = String(context.editorial.blocks.size);
  context.editorial.blocks.set(blockKey, annotation);
  return { children: renderMarkedInlines(block.inline, context, annotation.marks, { at: 0 }), blockKey };
}

function soleToken(inlines: MarkusInline[]): string | null {
  if (inlines.length !== 1 || inlines[0].type !== "text") return null;
  const text = inlines[0].text.trim();
  return WHOLE_TOKEN_PATTERN.test(text) ? text : null;
}

const HEADING_CLASSES = [
  "mt-5 mb-2 text-2xl font-semibold tracking-tight",
  "mt-5 mb-2 text-xl font-semibold tracking-tight",
  "mt-4 mb-2 text-lg font-semibold",
  "mt-4 mb-1 text-base font-semibold",
  "mt-3 mb-1 text-sm font-semibold",
  "mt-3 mb-1 text-sm font-medium",
];

function renderBlock(block: MarkusBlock, index: number, context: PreviewContext): ReactNode {
  switch (block.type) {
    case "paragraph": {
      const token = soleToken(block.inline);
      if (token && token in context.sidecar.images) return <div key={index}>{imagePlaceholder(token, context)}</div>;
      if (token && token in context.sidecar.citationLists) {
        return (
          <ol className="my-3 list-decimal space-y-1 pl-6 text-sm" data-markus-preview-bibliography key={index}>
            {context.sidecar.bibliography.map((entry, entryIndex) => (
              <li key={entryIndex}>{entry}</li>
            ))}
          </ol>
        );
      }
      const prose = proseInlines(block, context);
      return <p className="my-3 leading-relaxed" data-editorial-block={prose.blockKey} key={index}>{prose.children}</p>;
    }
    case "heading": {
      const level = Math.min(Math.max(block.level, 1), 6);
      const Tag = `h${level}` as "h1";
      const prose = proseInlines(block, context);
      return <Tag className={HEADING_CLASSES[level - 1]} data-editorial-block={prose.blockKey} key={index}>{prose.children}</Tag>;
    }
    case "list": {
      const items = block.items.map((item, itemIndex) => (
        <li key={itemIndex}>{renderBlocks(item.children, context)}</li>
      ));
      return block.ordered ? (
        <ol className="my-3 list-decimal space-y-1 pl-6" key={index} start={block.start ?? undefined}>{items}</ol>
      ) : (
        <ul className="my-3 list-disc space-y-1 pl-6" key={index}>{items}</ul>
      );
    }
    case "blockquote":
      return (
        <blockquote className="my-3 border-l-4 border-border pl-4 italic text-muted-foreground" key={index}>
          {renderBlocks(block.children, context)}
        </blockquote>
      );
    case "code":
      return (
        <pre className="my-3 overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs" key={index}>
          <code>{block.value}</code>
        </pre>
      );
    case "thematic_break":
      return <hr className="my-4 border-border" key={index} />;
    case "table":
      return (
        <div className="my-3 overflow-x-auto" key={index}>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                {block.header.map((cell, cellIndex) => (
                  <th className="border border-border bg-muted/40 px-2 py-1 text-left" key={cellIndex}>
                    {renderInlines(cell, context)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td className="border border-border px-2 py-1" key={cellIndex}>{renderInlines(cell, context)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "html":
      return (
        <pre className="my-3 overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs" key={index}>{block.value}</pre>
      );
  }
}

function normalizedFigureSource(src: string): string {
  return src.replace(/^(\.\.?\/)+/, "");
}

function renderFigure(directive: MarkusDirective, index: number, context: PreviewContext): ReactNode {
  const attribute = (name: string) => typeof directive.attributes[name] === "string" ? String(directive.attributes[name]) : "";
  const src = attribute("src");
  const alt = attribute("alt");
  const caption = attribute("caption");
  const credit = attribute("credit");
  const url = context.imageUrls[src] ?? context.imageUrls[normalizedFigureSource(src)];
  return (
    <figure className="my-4" data-markus-preview-directive="figure" key={index}>
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img alt={alt} className="h-auto max-w-full" data-markus-preview-image-loaded loading="lazy" src={url} />
      ) : (
        <div className="border border-dashed border-border bg-muted/30 px-3 py-6 text-center text-xs text-muted-foreground" data-markus-preview-image>
          {`Figure: ${src}${alt ? ` (${alt})` : ""}`}
        </div>
      )}
      {caption || credit ? (
        <figcaption className="mt-1 text-sm text-muted-foreground">
          {caption}{caption && credit ? " " : ""}{credit ? <span className="text-xs">{credit}</span> : null}
        </figcaption>
      ) : null}
    </figure>
  );
}

function renderDirective(directive: MarkusDirective, index: number, context: PreviewContext): ReactNode {
  if (directive.name === "pull-quote") {
    const attribution = directive.attributes.attribution;
    return (
      <blockquote
        className="my-4 border-y border-border px-4 py-3 text-lg font-medium italic"
        data-markus-preview-directive="pull-quote"
        key={index}
      >
        {renderBlocks(directive.children, context)}
        {typeof attribution === "string" && attribution ? (
          <footer className="mt-1 text-sm not-italic text-muted-foreground">{`— ${attribution}`}</footer>
        ) : null}
      </blockquote>
    );
  }
  if (directive.name === "figure") return renderFigure(directive, index, context);
  const dynamicRenderer = context.dynamicDirectives[directive.name];
  if (dynamicRenderer) return <div data-markus-preview-directive={directive.name} key={index}>{dynamicRenderer(directive.attributes)}</div>;
  const attributeEntries = Object.entries(directive.attributes).filter(([, value]) => value !== null && value !== "");
  return (
    <section
      className="my-3 rounded-lg border border-border"
      data-markus-preview-directive={directive.name}
      key={index}
    >
      <header className="border-b border-border bg-muted/40 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {directive.name}
      </header>
      <div className="px-3 py-1">
        {directive.leaf && attributeEntries.length > 0 ? (
          <p className="my-2 font-mono text-xs text-muted-foreground">
            {attributeEntries.map(([key, value]) => `${key}=${String(value)}`).join(" ")}
          </p>
        ) : null}
        {renderBlocks(directive.children, context)}
      </div>
    </section>
  );
}

function renderBlocks(nodes: MarkusNode[], context: PreviewContext): ReactNode[] {
  return nodes.map((node, index) =>
    node.type === "directive" ? renderDirective(node, index, context) : renderBlock(node, index, context),
  );
}

/** Characters of rendered text from the start of `block` to (node, offset), skipping citation and image furniture. */
function renderedOffset(block: HTMLElement, node: Node, offset: number): number {
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
  let total = 0;
  for (let current = walker.nextNode(); current; current = walker.nextNode()) {
    const skipped = current.parentElement?.closest("[data-editorial-skip]");
    if (current === node) return total + (skipped ? 0 : offset);
    if (!skipped) total += current.textContent?.length ?? 0;
  }
  return total;
}

function previewSelectionHandler(context: PreviewContext) {
  return (event: ReactMouseEvent<HTMLDivElement>) => {
    const editorial = context.editorial;
    if (!editorial?.onSelectSource) return;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    const startBlock = (range.startContainer.parentElement ?? null)?.closest<HTMLElement>("[data-editorial-block]");
    const endBlock = (range.endContainer.parentElement ?? null)?.closest<HTMLElement>("[data-editorial-block]");
    if (!startBlock || startBlock !== endBlock || !event.currentTarget.contains(startBlock)) return;
    const annotation = editorial.blocks.get(startBlock.dataset.editorialBlock ?? "");
    const source = selectionToSource(annotation, {
      start: renderedOffset(startBlock, range.startContainer, range.startOffset),
      end: renderedOffset(startBlock, range.endContainer, range.endOffset),
    });
    if (source) editorial.onSelectSource(source, range.getBoundingClientRect());
  };
}

export function MarkusIrPreview({
  bodyIr,
  imageUrls = {},
  dynamicDirectives = {},
  renderLink,
  editorial,
}: {
  editorial?: PreviewEditorial;
  bodyIr: unknown;
  imageUrls?: Record<string, string>;
  /** Live components for leaf directives whose content the host app computes, keyed by directive name. */
  dynamicDirectives?: PreviewContext["dynamicDirectives"];
  renderLink?: PreviewContext["renderLink"];
}) {
  try {
    const envelope = typeof bodyIr === "string" ? JSON.parse(bodyIr) : bodyIr;
    if (!isRecord(envelope)) throw new Error("bodyIr must be a JSON object");
    const document = parseMarkusDocument(envelope.document);
    const sidecar = readSidecar(envelope);
    const context: PreviewContext = {
      sidecar,
      citationNumbers: numberCitationsByFirstAppearance(envelope.document, sidecar),
      imageUrls,
      dynamicDirectives,
      renderLink,
      editorial: editorial ? { ...editorial, plan: planPreview(document, editorial.result, editorial.findings), blocks: new Map() } : undefined,
    };
    return (
      <div data-markus-preview onMouseUp={editorial?.onSelectSource ? previewSelectionHandler(context) : undefined}>
        {renderBlocks(document.children, context)}
      </div>
    );
  } catch (error) {
    return (
      <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" data-markus-preview-error role="alert">
        {`The preview could not be rendered: ${error instanceof Error ? error.message : "unknown error"}`}
      </p>
    );
  }
}
