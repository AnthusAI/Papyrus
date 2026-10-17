/**
 * Reads the stored Markus body IR (`bodyIr`, the envelope written by
 * `derive_body` in src/papyrus_content/markus_renderer/derive.py) and projects
 * it into the flat structures the Pretext solver consumes. The solver input
 * (`Article.body: string[]`) is unchanged; only its source changed.
 *
 * There is no fallback: an envelope with an unknown schema version, or a
 * placeholder token that the envelope cannot resolve, throws `BodyIrError`.
 */

import { MarkusSchemaVersionError, parseMarkusDocument } from "./markus-ir";
import { projectMarkusDocumentToPretext } from "./markus-projection";

export class BodyIrError extends Error {}

export type BodyProjectionImage = {
  src: string;
  alt: string;
  caption?: string;
  credit?: string;
  layout?: string;
};

export type BodyProjection = {
  body: string[];
  pullQuotes: string[];
  imageSrcs: BodyProjectionImage[];
};

const SUPPORTED_ENVELOPE_SCHEMA_VERSION = 1;
const SUPPORTED_MARKUS_IR_SCHEMA_VERSION = 1;
const TOKEN_PATTERN = /PAPYRUSMARKUP\d{5}END/g;
const WHOLE_TOKEN_PATTERN = /^PAPYRUSMARKUP\d{5}END$/;

type PapyrusSidecar = {
  images: Record<string, Record<string, unknown>>;
  citations: Record<string, string[]>;
  citationLists: Record<string, unknown>;
  bibliography: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseEnvelope(raw: unknown): Record<string, unknown> {
  let value = raw;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      throw new BodyIrError("bodyIr is not valid JSON");
    }
  }
  if (!isRecord(value)) throw new BodyIrError("bodyIr must be a JSON object");
  return value;
}

function readSidecar(envelope: Record<string, unknown>): PapyrusSidecar {
  const sidecar = envelope.papyrus;
  if (!isRecord(sidecar)) throw new BodyIrError("bodyIr.papyrus is missing");
  const { images, citations, citationLists, bibliography } = sidecar;
  if (!isRecord(images) || !isRecord(citations) || !isRecord(citationLists) || !Array.isArray(bibliography)) {
    throw new BodyIrError("bodyIr.papyrus must contain images, citations, citationLists and bibliography");
  }
  return {
    images: images as PapyrusSidecar["images"],
    citations: citations as PapyrusSidecar["citations"],
    citationLists: citationLists,
    bibliography: bibliography.map(String),
  };
}

function numberCitationKeysByFirstAppearance(document: unknown, sidecar: PapyrusSidecar): Map<string, number> {
  const numbers = new Map<string, number>();
  for (const token of JSON.stringify(document).match(TOKEN_PATTERN) ?? []) {
    for (const key of sidecar.citations[token] ?? []) {
      if (!numbers.has(key)) numbers.set(key, numbers.size + 1);
    }
  }
  return numbers;
}

function resolveCitationTokens(text: string, sidecar: PapyrusSidecar, numbers: Map<string, number>): string {
  return text.replace(TOKEN_PATTERN, (token) => {
    const keys = sidecar.citations[token];
    if (!keys) return token;
    return keys.map((key) => `[${numbers.get(key)}]`).join("");
  });
}

function imageFromSidecar(token: string, sidecar: PapyrusSidecar): BodyProjectionImage {
  const entry = sidecar.images[token];
  if (typeof entry?.src !== "string" || !entry.src) {
    throw new BodyIrError(`bodyIr image ${token} has no src`);
  }
  const image: BodyProjectionImage = { src: entry.src, alt: typeof entry.alt === "string" ? entry.alt : "" };
  if (typeof entry.caption === "string" && entry.caption) image.caption = entry.caption;
  if (typeof entry.credit === "string" && entry.credit) image.credit = entry.credit;
  if (typeof entry.layout === "string" && entry.layout) image.layout = entry.layout;
  return image;
}

export function projectBodyIr(raw: unknown): BodyProjection {
  const envelope = parseEnvelope(raw);
  if (envelope.schemaVersion !== SUPPORTED_ENVELOPE_SCHEMA_VERSION) {
    throw new BodyIrError(
      `bodyIr schemaVersion ${String(envelope.schemaVersion)} is not supported (expected ${SUPPORTED_ENVELOPE_SCHEMA_VERSION})`,
    );
  }
  const markus = envelope.markus;
  if (!isRecord(markus) || markus.irSchemaVersion !== SUPPORTED_MARKUS_IR_SCHEMA_VERSION) {
    throw new BodyIrError(
      `bodyIr markus.irSchemaVersion ${String(isRecord(markus) ? markus.irSchemaVersion : undefined)} is not supported (expected ${SUPPORTED_MARKUS_IR_SCHEMA_VERSION})`,
    );
  }
  const sidecar = readSidecar(envelope);

  let projected;
  try {
    projected = projectMarkusDocumentToPretext(parseMarkusDocument(envelope.document));
  } catch (error) {
    if (error instanceof MarkusSchemaVersionError) throw new BodyIrError(error.message);
    throw error;
  }

  const numbers = numberCitationKeysByFirstAppearance(envelope.document, sidecar);
  const body: string[] = [];
  const imageSrcs: BodyProjectionImage[] = [];
  for (const paragraph of projected.body) {
    if (WHOLE_TOKEN_PATTERN.test(paragraph) && paragraph in sidecar.images) {
      imageSrcs.push(imageFromSidecar(paragraph, sidecar));
      continue;
    }
    if (WHOLE_TOKEN_PATTERN.test(paragraph) && paragraph in sidecar.citationLists) {
      sidecar.bibliography.forEach((entry, index) => body.push(`${index + 1}. ${entry}`));
      continue;
    }
    body.push(resolveCitationTokens(paragraph, sidecar, numbers));
  }
  const pullQuotes = projected.pullQuotes.map((quote) => resolveCitationTokens(quote, sidecar, numbers));

  if ([...body, ...pullQuotes].some((text) => /PAPYRUSMARKUP\d{5}END/.test(text))) {
    throw new BodyIrError("bodyIr contains a placeholder token with no entry in bodyIr.papyrus");
  }
  return { body, pullQuotes, imageSrcs };
}

export type BodyImageMatch =
  | { kind: "media"; mediaIndex: number }
  | { kind: "external"; image: BodyProjectionImage };

/**
 * Matches each image the body references to a stored media row by the
 * `srcPath` the row was created from. Absolute http(s) sources need no media
 * row. Any other source without a row is an error, never skipped.
 */
export function matchBodyImages(
  imageSrcs: BodyProjectionImage[],
  mediaSrcPaths: Array<string | null>,
): BodyImageMatch[] {
  return imageSrcs.map((image) => {
    const mediaIndex = mediaSrcPaths.indexOf(image.src);
    if (mediaIndex >= 0) return { kind: "media", mediaIndex };
    if (/^https?:\/\//i.test(image.src)) return { kind: "external", image };
    throw new BodyIrError(`bodyIr references image "${image.src}" but no media asset has that srcPath`);
  });
}
