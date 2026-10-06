import type { ReactNode } from "react";
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

type PreviewContext = {
  sidecar: PreviewSidecar;
  citationNumbers: Map<string, number>;
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
      <sup className="text-primary" key={`${index}-${token}`}>
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
      case "link":
        return node.href ? (
          <a className="text-primary underline" href={node.href} key={index} rel="noopener noreferrer" target="_blank">
            {renderInlines(node.children, context)}
          </a>
        ) : (
          <span key={index}>{renderInlines(node.children, context)}</span>
        );
      case "image":
        return (
          <span className="rounded border border-dashed border-border px-1 text-xs text-muted-foreground" key={index}>
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
      return <p className="my-3 leading-relaxed" key={index}>{renderInlines(block.inline, context)}</p>;
    }
    case "heading": {
      const level = Math.min(Math.max(block.level, 1), 6);
      const Tag = `h${level}` as "h1";
      return <Tag className={HEADING_CLASSES[level - 1]} key={index}>{renderInlines(block.inline, context)}</Tag>;
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

export function MarkusIrPreview({ bodyIr }: { bodyIr: unknown }) {
  try {
    const envelope = typeof bodyIr === "string" ? JSON.parse(bodyIr) : bodyIr;
    if (!isRecord(envelope)) throw new Error("bodyIr must be a JSON object");
    const document = parseMarkusDocument(envelope.document);
    const sidecar = readSidecar(envelope);
    const context: PreviewContext = {
      sidecar,
      citationNumbers: numberCitationsByFirstAppearance(envelope.document, sidecar),
    };
    return <div data-markus-preview>{renderBlocks(document.children, context)}</div>;
  } catch (error) {
    return (
      <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" data-markus-preview-error role="alert">
        {`The preview could not be rendered: ${error instanceof Error ? error.message : "unknown error"}`}
      </p>
    );
  }
}
