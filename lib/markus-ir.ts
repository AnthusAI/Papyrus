/**
 * Typed TypeScript mirror of the Markus document IR (`markus ast`, Markus
 * repo branch `feature/document-ir`, `src/markusmd/ast.py` +
 * `src/markusmd/blocks.py`).
 *
 * This is NOT invented from the Markus language docs -- it is typed
 * directly from a real `markus ast` invocation (see
 * `scripts/fixtures/markus-sample.ast.json`, captured from
 * `scripts/fixtures/markus-sample.md` via `markus ast`) cross-checked
 * against the emitting Python dataclasses' `to_dict()` methods. Papyrus
 * does NOT re-parse Markdown; it only ingests this JSON shape.
 *
 * `IR_SCHEMA_VERSION` mirrors `markusmd.blocks.IR_SCHEMA_VERSION`. Bump it
 * only in lockstep with a corresponding bump on the Markus side, and only
 * after re-deriving the types below from a fresh `markus ast` capture --
 * never by hand-editing the number.
 */

/** The Markus document IR schema version Papyrus is typed against. */
export const MARKUS_IR_SCHEMA_VERSION = 1 as const;

// --------------------------------------------------------------------------
// Inline nodes (markusmd/blocks.py: Text | Emphasis | Strong | Strikethrough
// | CodeSpan | Link | Image | SoftBreak | HardBreak | HtmlInline)
// --------------------------------------------------------------------------

export type MarkusInlineText = { type: "text"; text: string };

export type MarkusInlineEmphasis = { type: "emphasis"; children: MarkusInline[] };

export type MarkusInlineStrong = { type: "strong"; children: MarkusInline[] };

export type MarkusInlineStrikethrough = { type: "strikethrough"; children: MarkusInline[] };

/**
 * An inline code span, e.g. `` `code` ``. Distinct from the block-level
 * `code` node (`MarkusCodeBlock`, type `"code"`) below -- do not conflate
 * the two. `code_span` never has a `lang`; it is always plain text.
 */
export type MarkusInlineCodeSpan = { type: "code_span"; code: string };

export type MarkusInlineLink = {
  type: "link";
  href: string | null;
  title: string | null;
  children: MarkusInline[];
};

export type MarkusInlineImage = {
  type: "image";
  src: string | null;
  alt: string;
  title: string | null;
};

export type MarkusInlineSoftBreak = { type: "soft_break" };

export type MarkusInlineHardBreak = { type: "hard_break" };

/**
 * Raw inline HTML. Only produced when the document was parsed with
 * `allow_html=True` (`markus ast --allow-html`). Papyrus builds fragments
 * with `--allow-html` OFF (see docs/pluggable-publishers security note), so
 * this node type should not appear in IR Papyrus ingests in practice; it is
 * still typed here because the emitter can produce it, and the projection
 * must not silently drop it if it ever does.
 */
export type MarkusInlineHtml = { type: "html_inline"; value: string };

export type MarkusInline =
  | MarkusInlineText
  | MarkusInlineEmphasis
  | MarkusInlineStrong
  | MarkusInlineStrikethrough
  | MarkusInlineCodeSpan
  | MarkusInlineLink
  | MarkusInlineImage
  | MarkusInlineSoftBreak
  | MarkusInlineHardBreak
  | MarkusInlineHtml;

// --------------------------------------------------------------------------
// Typed Markdown block nodes (markusmd/blocks.py: Heading | Paragraph |
// List | Blockquote | CodeBlock | ThematicBreak | HtmlBlock | Table).
// These sit as ordered PEERS of directive nodes in one children[] array --
// there is no opaque raw-markdown node in the IR.
// --------------------------------------------------------------------------

export type MarkusHeading = {
  type: "heading";
  level: number;
  inline: MarkusInline[];
  line: number | null;
};

export type MarkusParagraph = {
  type: "paragraph";
  inline: MarkusInline[];
  line: number | null;
};

export type MarkusListItem = {
  type: "list_item";
  checked: boolean | null;
  children: MarkusBlock[];
  line: number | null;
};

export type MarkusList = {
  type: "list";
  ordered: boolean;
  start: number | null;
  items: MarkusListItem[];
  line: number | null;
};

export type MarkusBlockquote = {
  type: "blockquote";
  children: MarkusBlock[];
  line: number | null;
};

/**
 * A fenced or indented code BLOCK. Distinct from the inline `code_span`
 * node above -- do not conflate the two.
 */
export type MarkusCodeBlock = {
  type: "code";
  lang: string | null;
  value: string;
  line: number | null;
};

export type MarkusThematicBreak = { type: "thematic_break"; line: number | null };

/**
 * A raw HTML block. Only produced when `allow_html=True`; see
 * `MarkusInlineHtml` above for why Papyrus's build should never emit this
 * in the IR it ingests, and why it is still typed and handled anyway.
 */
export type MarkusHtmlBlock = { type: "html"; value: string; line: number | null };

export type MarkusTable = {
  type: "table";
  align: Array<string | null>;
  header: MarkusInline[][];
  rows: MarkusInline[][][];
  line: number | null;
};

export type MarkusBlock =
  | MarkusHeading
  | MarkusParagraph
  | MarkusList
  | MarkusBlockquote
  | MarkusCodeBlock
  | MarkusThematicBreak
  | MarkusHtmlBlock
  | MarkusTable;

// --------------------------------------------------------------------------
// Directives (markusmd/ast.py: Directive). Container directives have
// `leaf: false` and nest further nodes; leaf directives (`metric`, `video`)
// have `leaf: true` and always `children: []`. `attributes` is whatever the
// directive's validated attribute schema produced -- Papyrus treats it as
// an open record rather than typing every directive's attribute set, since
// the vocabulary (and its attributes) are owned and validated by Markus,
// not re-specified here.
// --------------------------------------------------------------------------

export type MarkusDirectiveAttributes = Record<string, string | number | boolean | null>;

export type MarkusDirective = {
  type: "directive";
  name: string;
  attributes: MarkusDirectiveAttributes;
  leaf: boolean;
  line: number;
  children: MarkusNode[];
};

/** A document child: a typed Markdown block or a directive, in document order. */
export type MarkusNode = MarkusBlock | MarkusDirective;

// --------------------------------------------------------------------------
// Document root (markusmd/ast.py: Document.to_dict()).
// --------------------------------------------------------------------------

export type MarkusFrontMatter = Record<string, unknown>;

export type MarkusDocument = {
  type: "document";
  schema_version: number;
  front_matter: MarkusFrontMatter;
  children: MarkusNode[];
};

/**
 * Thrown when ingested IR declares a `schema_version` this module was not
 * typed against. This is the "fail loudly on mismatch" boundary check
 * required before any projection runs -- silently proceeding against an
 * unknown shape would risk mis-typed access on fields that changed shape.
 */
export class MarkusSchemaVersionError extends Error {
  constructor(public readonly received: unknown) {
    super(
      `Markus document IR schema_version mismatch: this build understands ` +
        `schema_version ${MARKUS_IR_SCHEMA_VERSION}, but received ` +
        `${JSON.stringify(received)}. Re-derive lib/markus-ir.ts from a fresh ` +
        `\`markus ast\` capture before ingesting this document.`,
    );
    this.name = "MarkusSchemaVersionError";
  }
}

/**
 * Parse + validate a raw `markus ast` JSON payload into a typed
 * `MarkusDocument`, checking `schema_version` at the boundary. This is the
 * only place Papyrus should accept untyped Markus IR JSON -- everything
 * downstream (the Pretext projection, a future Markus build step) should
 * consume the typed `MarkusDocument` this returns, never raw `unknown`.
 */
export function parseMarkusDocument(raw: unknown): MarkusDocument {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("Markus document IR must be a JSON object");
  }
  const candidate = raw as Record<string, unknown>;
  if (candidate.type !== "document") {
    throw new Error(`Expected Markus IR root node of type "document", got ${JSON.stringify(candidate.type)}`);
  }
  if (candidate.schema_version !== MARKUS_IR_SCHEMA_VERSION) {
    throw new MarkusSchemaVersionError(candidate.schema_version);
  }
  return candidate as MarkusDocument;
}
