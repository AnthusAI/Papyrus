const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const YAML = require("yaml");

const DOI_PATTERN = /\b10\.\d{4,9}\/[-._;()/:A-Z0-9]+\b/i;
const ARXIV_MODERN_PATTERN = /\b([0-9]{4}\.[0-9]{4,5})(v\d+)?\b/i;
const ARXIV_LEGACY_PATTERN = /\b([a-z-]+(?:\.[A-Z]{2})?\/[0-9]{7})(v\d+)?\b/i;
const USER_AGENT = "papyrus-identifier-backfill/1.0";

const IDENTIFIER_TYPES = ["doi", "arxiv_id", "isbn13", "publisher_item"];

const IDENTIFIER_TYPE_CONFIG = {
  doi: {
    nodePrefix: "doi",
    relationTypeKey: "digital_object_identifier_is",
    metadataKey: "doi",
    label: "Digital Object Identifier",
  },
  arxiv_id: {
    nodePrefix: "arxiv",
    relationTypeKey: "arxiv_identifier_is",
    metadataKey: "arxiv_id",
    label: "arXiv identifier",
  },
  isbn13: {
    nodePrefix: "isbn13",
    relationTypeKey: "isbn_identifier_is",
    metadataKey: "isbn13",
    label: "ISBN-13 identifier",
  },
  publisher_item: {
    nodePrefix: "publisher_item",
    relationTypeKey: "publisher_item_identifier_is",
    metadataKey: "publisher_item",
    label: "publisher item identifier",
  },
};

function normalizeText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function hashShort(value) {
  return crypto.createHash("sha256").update(typeof value === "string" ? value : JSON.stringify(value)).digest("hex").slice(0, 16);
}

function normalizeDoi(value) {
  const text = normalizeText(value);
  if (!text) return null;
  const stripped = text
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "")
    .replace(/^doi:\s*/i, "")
    .trim();
  const match = stripped.match(DOI_PATTERN);
  if (!match) return null;
  return match[0]
    .replace(/[)>.,;]+$/g, "")
    .toLowerCase();
}

function extractDoiFromText(value) {
  return normalizeDoi(value);
}

function normalizeArxivId(value) {
  const text = normalizeText(value);
  if (!text) return null;
  const sources = [text];
  try {
    const parsed = new URL(text);
    if (/^www\./i.test(parsed.hostname) || parsed.hostname === "arxiv.org") {
      sources.push(parsed.pathname);
    }
  } catch {
    // Plain ids are valid input.
  }
  for (const source of sources) {
    const cleaned = source
      .replace(/^arxiv:\s*/i, "")
      .replace(/^\/+(abs|pdf|html|src)\//i, "")
      .replace(/\.pdf$/i, "")
      .replace(/\/+$/g, "");
    const modern = cleaned.match(ARXIV_MODERN_PATTERN);
    if (modern) return modern[1].toLowerCase();
    const legacy = cleaned.match(ARXIV_LEGACY_PATTERN);
    if (legacy) return legacy[1].toLowerCase();
  }
  return null;
}

function extractArxivVersion(value) {
  const text = normalizeText(value);
  if (!text) return null;
  const match = text.match(ARXIV_MODERN_PATTERN) ?? text.match(ARXIV_LEGACY_PATTERN);
  return match?.[2] ? match[2].toLowerCase() : null;
}

function extractArxivId(value) {
  return normalizeArxivId(value);
}

function normalizeIsbn13(value) {
  const text = normalizeText(value);
  if (!text) return null;
  const raw = text.replace(/[^0-9Xx]/g, "").toUpperCase();
  if (raw.length === 13 && /^[0-9]{13}$/.test(raw) && isValidIsbn13(raw)) return raw;
  if (raw.length === 10 && /^[0-9]{9}[0-9X]$/.test(raw) && isValidIsbn10(raw)) {
    return isbn10ToIsbn13(raw);
  }
  return null;
}

function isValidIsbn10(value) {
  let sum = 0;
  for (let index = 0; index < 10; index += 1) {
    const char = value[index];
    const digit = char === "X" ? 10 : Number(char);
    if (!Number.isInteger(digit)) return false;
    sum += digit * (10 - index);
  }
  return sum % 11 === 0;
}

function isValidIsbn13(value) {
  let sum = 0;
  for (let index = 0; index < 13; index += 1) {
    const digit = Number(value[index]);
    if (!Number.isInteger(digit)) return false;
    sum += digit * (index % 2 === 0 ? 1 : 3);
  }
  return sum % 10 === 0;
}

function isbn10ToIsbn13(value) {
  const body = `978${value.slice(0, 9)}`;
  let sum = 0;
  for (let index = 0; index < body.length; index += 1) {
    sum += Number(body[index]) * (index % 2 === 0 ? 1 : 3);
  }
  const check = (10 - (sum % 10)) % 10;
  return `${body}${check}`;
}

function normalizePublisherItem(value) {
  const text = normalizeText(value);
  if (!text) return null;
  const candidate = publisherItemFromUri(text) ?? text;
  return candidate
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/^www\./, "")
    .replace(/[?#].*$/g, "")
    .replace(/\/+$/g, "")
    .replace(/[^a-z0-9._:/-]+/g, "-")
    .replace(/-+/g, "-")
    .slice(0, 240) || null;
}

function publisherItemFromUri(value) {
  try {
    const parsed = new URL(value);
    if (!/^https?:$/i.test(parsed.protocol)) return null;
    const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
    const pathname = parsed.pathname.replace(/\/+$/g, "");
    const acl = pathname.match(/^\/([0-9]{4}\.[a-z0-9-]+\.[0-9]+)(?:\.pdf)?$/i);
    if (host === "aclanthology.org" && acl) return `aclanthology:${acl[1].toLowerCase()}`;
    if (host === "openreview.net") {
      const id = parsed.searchParams.get("id") || pathname.match(/\/pdf\/([^/]+)$/i)?.[1];
      if (id) return `openreview:${id}`;
    }
    if (host === "neurips.cc") {
      const poster = pathname.match(/\/poster\/([^/]+)$/i)?.[1];
      if (poster) return `neurips-poster:${poster}`;
    }
    if (host === "semanticscholar.org") {
      const paper = pathname.match(/\/paper\/(?:[^/]+\/)?([a-f0-9]{20,})/i)?.[1];
      if (paper) return `semanticscholar:${paper.toLowerCase()}`;
    }
    if (host === "dl.acm.org") {
      const doiPath = pathname.match(/\/doi\/(?:abs|fullHtml|pdf)?\/?(10\..+)$/i)?.[1];
      if (doiPath) return `acm:${normalizeDoi(doiPath) ?? doiPath.toLowerCase()}`;
    }
    return `${host}${pathname}`.replace(/\/+$/g, "");
  } catch {
    return null;
  }
}

function normalizeIdentifier(type, value) {
  switch (type) {
    case "doi":
      return normalizeDoi(value);
    case "arxiv_id":
      return normalizeArxivId(value);
    case "isbn13":
      return normalizeIsbn13(value);
    case "publisher_item":
      return normalizePublisherItem(value);
    default:
      return null;
  }
}

function identifierNodeKey(type, value) {
  const config = IDENTIFIER_TYPE_CONFIG[type];
  const normalized = normalizeIdentifier(type, value);
  return config && normalized ? `${config.nodePrefix}:${normalized}` : null;
}

function normalizeIdentifierTypes(value, { defaultTypes = ["doi"] } = {}) {
  const raw = Array.isArray(value)
    ? value
    : normalizeText(value)
      ? normalizeText(value).split(",")
      : defaultTypes;
  const types = [];
  for (const entry of raw) {
    const normalized = normalizeText(entry).toLowerCase().replace(/-/g, "_");
    if (!normalized) continue;
    const type = normalized === "arxiv" ? "arxiv_id" : normalized === "isbn" ? "isbn13" : normalized;
    if (!IDENTIFIER_TYPES.includes(type)) throw new Error(`Unsupported identifier type: ${entry}.`);
    if (!types.includes(type)) types.push(type);
  }
  return types.length ? types : [...defaultTypes];
}

function tokenize(value) {
  return normalizeText(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .split(/\s+/)
    .filter(Boolean);
}

function jaccardSimilarity(left, right) {
  const leftSet = new Set(tokenize(left));
  const rightSet = new Set(tokenize(right));
  if (!leftSet.size || !rightSet.size) return 0;
  let overlap = 0;
  for (const token of leftSet) {
    if (rightSet.has(token)) overlap += 1;
  }
  const union = new Set([...leftSet, ...rightSet]).size;
  return union ? overlap / union : 0;
}

function toYear(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).slice(0, 4));
  if (!Number.isInteger(parsed) || parsed < 1900 || parsed > 2100) return null;
  return parsed;
}

function listAuthors(value) {
  if (Array.isArray(value)) return value.map((entry) => normalizeText(entry)).filter(Boolean);
  if (typeof value === "string") return value.split(/[;,]/).map((entry) => normalizeText(entry)).filter(Boolean);
  return [];
}

function listAuthorTokens(value) {
  const tokens = new Set();
  for (const author of listAuthors(value)) {
    for (const token of tokenize(author)) tokens.add(token);
  }
  return tokens;
}

function authorOverlap(referenceAuthors, candidateAuthors) {
  const left = listAuthorTokens(referenceAuthors);
  const right = listAuthorTokens(candidateAuthors);
  if (!left.size || !right.size) return 0;
  let overlap = 0;
  for (const token of left) {
    if (right.has(token)) overlap += 1;
  }
  return overlap / Math.max(left.size, right.size);
}

function defaultFetcher(url, options = {}) {
  return fetch(url, options);
}

async function fetchJson(url, { fetcher = defaultFetcher, errors = [], stage }) {
  try {
    const response = await fetcher(url, {
      headers: {
        Accept: "application/json",
        "User-Agent": USER_AGENT,
      },
    });
    if (!response.ok) {
      errors.push({ stage, url, status: response.status, statusText: response.statusText });
      return null;
    }
    return await response.json();
  } catch (error) {
    errors.push({ stage, url, error: error instanceof Error ? error.message : String(error) });
    return null;
  }
}

function candidateBaseScore(source) {
  switch (source) {
    case "metadata":
      return 100;
    case "source_uri":
      return 97;
    case "catalog":
      return 94;
    case "sidecar":
      return 92;
    case "openalex_arxiv":
    case "openalex_doi":
      return 88;
    case "openalex_search":
      return 80;
    case "crossref_search":
      return 74;
    case "publisher_uri":
      return 70;
    default:
      return 50;
  }
}

function buildCandidate(input) {
  const type = input.type;
  const value = normalizeIdentifier(type, input.value);
  if (!type || !value) return null;
  return {
    type,
    value,
    doi: type === "doi" ? value : undefined,
    arxiv_id: type === "arxiv_id" ? value : undefined,
    isbn13: type === "isbn13" ? value : undefined,
    publisher_item: type === "publisher_item" ? value : undefined,
    source: input.source,
    title: normalizeText(input.title) || null,
    year: toYear(input.year),
    authors: listAuthors(input.authors),
    evidence: normalizeText(input.evidence) || null,
    version: input.version ?? null,
    baseScore: Number(input.baseScore ?? candidateBaseScore(input.source)),
  };
}

function dedupeCandidates(candidates) {
  const byValue = new Map();
  for (const candidate of candidates) {
    if (!candidate?.type || !candidate?.value) continue;
    const key = `${candidate.type}:${candidate.value}`;
    const existing = byValue.get(key);
    if (!existing) {
      byValue.set(key, { ...candidate, sources: [candidate.source], evidences: candidate.evidence ? [candidate.evidence] : [] });
      continue;
    }
    if (candidate.baseScore > existing.baseScore) {
      existing.baseScore = candidate.baseScore;
      existing.title = candidate.title || existing.title;
      existing.year = candidate.year ?? existing.year;
      existing.authors = candidate.authors?.length ? candidate.authors : existing.authors;
      existing.version = candidate.version ?? existing.version;
    }
    if (candidate.source && !existing.sources.includes(candidate.source)) existing.sources.push(candidate.source);
    if (candidate.evidence && !existing.evidences.includes(candidate.evidence)) existing.evidences.push(candidate.evidence);
  }
  return Array.from(byValue.values());
}

function scoreCandidates(reference, candidates) {
  const referenceTitle = normalizeText(reference.title);
  const referenceYear = toYear(reference.sourcePublishedAt) ?? toYear(reference.metadata?.year);
  const referenceAuthors = listAuthors(reference.authors);
  return candidates
    .map((candidate) => {
      const titleSimilarity = referenceTitle && candidate.title ? jaccardSimilarity(referenceTitle, candidate.title) : 0;
      const yearDelta = referenceYear && candidate.year ? Math.abs(referenceYear - candidate.year) : null;
      const authorSimilarity = referenceAuthors.length && candidate.authors?.length ? authorOverlap(referenceAuthors, candidate.authors) : 0;
      let score = candidate.baseScore;
      score += Math.round(titleSimilarity * 20);
      if (yearDelta === 0) score += 6;
      else if (yearDelta === 1) score += 3;
      else if (yearDelta !== null && yearDelta > 1) score -= 4;
      score += Math.round(authorSimilarity * 8);
      return { ...candidate, score, titleSimilarity, yearDelta, authorSimilarity };
    })
    .sort((left, right) => right.score - left.score || String(left.value).localeCompare(String(right.value)));
}

function acceptedCandidate(scored) {
  if (!scored.length) return null;
  const top = scored[0];
  const second = scored[1] ?? null;
  if (top.score >= 96) return top;
  if (top.score >= 90 && (!second || top.score - second.score >= 8)) return top;
  if (top.score >= 84 && !second && top.sources.some((source) => ["metadata", "source_uri", "catalog", "sidecar"].includes(source))) return top;
  if (top.type === "publisher_item" && top.score >= 70 && !second) return top;
  return null;
}

async function lookupOpenAlexByArxiv(arxivId, { fetcher, errors, type = "doi" }) {
  if (!arxivId) return [];
  const url = `https://api.openalex.org/works?per-page=5&filter=ids.arxiv:${encodeURIComponent(arxivId)}`;
  const payload = await fetchJson(url, { fetcher, errors, stage: "openalex_arxiv" });
  const results = Array.isArray(payload?.results) ? payload.results : [];
  return results.flatMap((work) => candidatesFromOpenAlexWork(work, type, "openalex_arxiv"));
}

async function lookupOpenAlexByDoi(doi, { fetcher, errors, type = "arxiv_id" }) {
  if (!doi) return [];
  const url = `https://api.openalex.org/works?per-page=5&filter=doi:${encodeURIComponent(doi)}`;
  const payload = await fetchJson(url, { fetcher, errors, stage: "openalex_doi" });
  const results = Array.isArray(payload?.results) ? payload.results : [];
  return results.flatMap((work) => candidatesFromOpenAlexWork(work, type, "openalex_doi"));
}

async function lookupOpenAlexByTitle(reference, { fetcher, errors, type }) {
  if (!normalizeText(reference.title)) return [];
  const url = `https://api.openalex.org/works?per-page=8&search=${encodeURIComponent(reference.title)}`;
  const payload = await fetchJson(url, { fetcher, errors, stage: "openalex_search" });
  const results = Array.isArray(payload?.results) ? payload.results : [];
  return results.flatMap((work) => candidatesFromOpenAlexWork(work, type, "openalex_search"));
}

async function lookupCrossrefByTitle(reference, { fetcher, errors, type = "doi" }) {
  if (type !== "doi") return [];
  if (!normalizeText(reference.title)) return [];
  const url = `https://api.crossref.org/works?rows=8&query.bibliographic=${encodeURIComponent(reference.title)}`;
  const payload = await fetchJson(url, { fetcher, errors, stage: "crossref_search" });
  const items = Array.isArray(payload?.message?.items) ? payload.message.items : [];
  return items
    .map((item) => buildCandidate({
      type: "doi",
      source: "crossref_search",
      value: item?.DOI,
      title: Array.isArray(item?.title) ? item.title[0] : item?.title,
      year: item?.issued?.["date-parts"]?.[0]?.[0],
      authors: (item?.author ?? []).map((entry) => `${entry?.given ?? ""} ${entry?.family ?? ""}`.trim()).filter(Boolean),
      evidence: item?.URL ?? null,
    }))
    .filter(Boolean);
}

function candidatesFromOpenAlexWork(work, type, source) {
  const values = {
    doi: work?.doi ?? work?.ids?.doi,
    arxiv_id: work?.ids?.arxiv,
  };
  const value = values[type];
  if (!value) return [];
  const candidate = buildCandidate({
    type,
    source,
    value,
    title: work?.title,
    year: work?.publication_year,
    authors: (work?.authorships ?? []).map((entry) => entry?.author?.display_name).filter(Boolean),
    evidence: work?.id ?? null,
    version: type === "arxiv_id" ? extractArxivVersion(value) : null,
  });
  return candidate ? [candidate] : [];
}

function parseCatalogItems(corpusPath) {
  const catalogCandidates = [
    path.join(corpusPath, "metadata", "catalog.json"),
    path.join(corpusPath, "catalog.json"),
    path.join(corpusPath, "imports", "catalog.json"),
  ];
  const catalogPath = catalogCandidates.find((entry) => fs.existsSync(entry));
  if (!catalogPath) return { catalogPath: null, byItemId: new Map() };
  const parsed = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
  const items = Array.isArray(parsed?.items)
    ? parsed.items
    : parsed?.items && typeof parsed.items === "object"
      ? Object.values(parsed.items)
      : [];
  const byItemId = new Map();
  for (const item of items) {
    const itemId = normalizeText(item.item_id ?? item.itemId ?? item.id);
    if (!itemId) continue;
    byItemId.set(itemId, { item, identifiers: identifiersFromObject(item) });
  }
  return { catalogPath, byItemId };
}

function parseYaml(pathname) {
  try {
    return YAML.parse(fs.readFileSync(pathname, "utf8")) ?? {};
  } catch {
    return {};
  }
}

function sidecarIdentifier(sidecarPath, type) {
  if (!sidecarPath || !fs.existsSync(sidecarPath)) return null;
  return identifiersFromObject(parseYaml(sidecarPath))[type] ?? null;
}

function sidecarDoi(sidecarPath) {
  return sidecarIdentifier(sidecarPath, "doi");
}

function identifiersFromObject(value) {
  const source = value && typeof value === "object" ? value : {};
  return {
    doi: normalizeDoi(
      source.doi
      ?? source.metadata?.doi
      ?? source.metadata?.source_doi
      ?? source.metadata?.identifiers?.doi
      ?? source.identifiers?.doi
      ?? source.identifier?.doi
      ?? "",
    ),
    arxiv_id: normalizeArxivId(
      source.arxiv_id
      ?? source.arxivId
      ?? source.metadata?.arxiv_id
      ?? source.metadata?.arxivId
      ?? source.metadata?.identifiers?.arxiv_id
      ?? source.metadata?.identifiers?.arxivId
      ?? source.identifiers?.arxiv_id
      ?? source.identifiers?.arxivId
      ?? "",
    ),
    isbn13: normalizeIsbn13(
      source.isbn13
      ?? source.isbn
      ?? source.metadata?.isbn13
      ?? source.metadata?.isbn
      ?? source.metadata?.identifiers?.isbn13
      ?? source.metadata?.identifiers?.isbn
      ?? source.identifiers?.isbn13
      ?? source.identifiers?.isbn
      ?? "",
    ),
    publisher_item: normalizePublisherItem(
      source.publisher_item
      ?? source.publisherItem
      ?? source.metadata?.publisher_item
      ?? source.metadata?.publisherItem
      ?? source.metadata?.identifiers?.publisher_item
      ?? source.metadata?.identifiers?.publisherItem
      ?? source.identifiers?.publisher_item
      ?? source.identifiers?.publisherItem
      ?? "",
    ),
  };
}

function createCandidateFromLocalMetadata(type, reference, metadata, catalogEntry, sidecarValue) {
  const candidates = [];
  const referenceIdentifiers = identifiersFromObject({ ...reference, metadata });
  const metadataIdentifiers = identifiersFromObject(metadata);
  const catalogIdentifiers = catalogEntry?.identifiers ?? {};
  const sidecarIdentifierValue = normalizeIdentifier(type, sidecarValue);
  const localValues = [
    ["metadata", metadataIdentifiers[type] ?? referenceIdentifiers[type]],
    ["source_uri", identifierFromSourceUri(type, reference.sourceUri)],
    ["catalog", catalogIdentifiers[type]],
    ["sidecar", sidecarIdentifierValue],
  ];
  for (const [source, value] of localValues) {
    if (!value) continue;
    candidates.push(buildCandidate({
      type,
      source,
      value,
      title: source === "catalog" ? catalogEntry?.item?.title ?? reference.title : reference.title,
      year: source === "catalog" ? catalogEntry?.item?.year ?? reference.sourcePublishedAt : reference.sourcePublishedAt,
      authors: source === "catalog" ? catalogEntry?.item?.authors ?? reference.authors : reference.authors,
      version: type === "arxiv_id" ? extractArxivVersion(value) : null,
    }));
  }
  return candidates.filter(Boolean);
}

function identifierFromSourceUri(type, sourceUri) {
  if (type === "doi") return normalizeDoi(sourceUri);
  if (type === "arxiv_id") return normalizeArxivId(sourceUri);
  if (type === "isbn13") return normalizeIsbn13(sourceUri);
  if (type === "publisher_item") return normalizePublisherItem(publisherItemFromUri(sourceUri));
  return null;
}

async function adjudicateWithOpenAi(reference, type, scoredCandidates, options = {}) {
  const apiKey = normalizeText(options.openaiApiKey ?? process.env.OPENAI_API_KEY);
  if (!apiKey || !scoredCandidates.length) return null;
  const model = normalizeText(options.model) || "gpt-6-luna";
  const effort = normalizeText(options.reasoningEffort) || "low";
  const response = await defaultFetcher("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      reasoning: { effort },
      input: [
        {
          role: "system",
          content: [{ type: "input_text", text: "Select the best identifier candidate for the reference. Return strict JSON only." }],
        },
        {
          role: "user",
          content: [{
            type: "input_text",
            text: JSON.stringify({
              identifierType: type,
              reference: {
                id: reference.id,
                title: reference.title,
                year: toYear(reference.sourcePublishedAt),
                authors: listAuthors(reference.authors),
                sourceUri: reference.sourceUri,
              },
              candidates: scoredCandidates.map((candidate) => ({
                value: candidate.value,
                score: candidate.score,
                source: candidate.sources ?? [candidate.source],
                title: candidate.title,
                year: candidate.year,
                authorSimilarity: candidate.authorSimilarity,
                titleSimilarity: candidate.titleSimilarity,
              })),
            }),
          }],
        },
      ],
      text: {
        format: {
          type: "json_schema",
          name: "identifier_adjudication",
          strict: true,
          schema: {
            type: "object",
            properties: {
              decision: { type: "string", enum: ["select", "none"] },
              value: { type: ["string", "null"] },
              doi: { type: ["string", "null"] },
              confidence: { type: "number" },
              rationale: { type: "string" },
            },
            required: ["decision", "value", "doi", "confidence", "rationale"],
            additionalProperties: false,
          },
        },
      },
    }),
  });
  if (!response.ok) return null;
  const payload = await response.json();
  const text = normalizeText(payload?.output_text);
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    const value = normalizeIdentifier(type, parsed?.value ?? parsed?.doi);
    if (parsed?.decision !== "select" || !value) return null;
    return {
      value,
      doi: type === "doi" ? value : undefined,
      confidence: Number(parsed?.confidence ?? 0),
      rationale: normalizeText(parsed?.rationale) || null,
      model,
      reasoningEffort: effort,
    };
  } catch {
    return null;
  }
}

async function resolveIdentifierForReference({
  type,
  reference,
  metadata = {},
  catalogEntry = null,
  sidecarValue = null,
  useLlm = false,
  openaiModel = null,
  openaiReasoningEffort = null,
  openaiApiKey = null,
  fetcher = defaultFetcher,
  llmAdjudicator = adjudicateWithOpenAi,
  errors = [],
}) {
  if (!IDENTIFIER_TYPES.includes(type)) throw new Error(`Unsupported identifier type: ${type}.`);
  const localCandidates = createCandidateFromLocalMetadata(type, reference, metadata, catalogEntry, sidecarValue);
  let candidates = [...localCandidates];
  const uniqueLocalValues = new Set(localCandidates.map((candidate) => candidate.value));
  if (uniqueLocalValues.size === 1 && localCandidates.length) {
    const only = [...uniqueLocalValues][0];
    return resolvedResult(type, only, {
      source: "deterministic_local",
      confidence: 1,
      llmUsed: false,
      candidates: dedupeCandidates(localCandidates),
      errors,
      rationale: "Local metadata/source URI/catalog/sidecar agreed on one identifier.",
      version: localCandidates.find((candidate) => candidate.value === only)?.version ?? null,
    });
  }

  if (type === "doi") {
    const arxivId = normalizeArxivId(reference.sourceUri ?? metadata?.arxiv_id ?? metadata?.arxivId ?? metadata?.identifiers?.arxiv_id ?? "");
    if (arxivId) candidates = candidates.concat(await lookupOpenAlexByArxiv(arxivId, { fetcher, errors, type: "doi" }));
    if (!localCandidates.length || uniqueLocalValues.size > 1) {
      candidates = candidates.concat(
        await lookupOpenAlexByTitle(reference, { fetcher, errors, type: "doi" }),
        await lookupCrossrefByTitle(reference, { fetcher, errors, type: "doi" }),
      );
    }
  } else if (type === "arxiv_id") {
    const doi = normalizeDoi(metadata?.doi ?? metadata?.identifiers?.doi ?? reference.sourceUri ?? "");
    if (doi) candidates = candidates.concat(await lookupOpenAlexByDoi(doi, { fetcher, errors, type: "arxiv_id" }));
    if (!localCandidates.length || uniqueLocalValues.size > 1) {
      candidates = candidates.concat(await lookupOpenAlexByTitle(reference, { fetcher, errors, type: "arxiv_id" }));
    }
  } else if (type === "publisher_item" && !localCandidates.length) {
    const value = identifierFromSourceUri(type, reference.sourceUri);
    if (value) candidates.push(buildCandidate({ type, source: "publisher_uri", value, title: reference.title, year: reference.sourcePublishedAt, authors: reference.authors }));
  }

  const deduped = dedupeCandidates(candidates);
  const scored = scoreCandidates({ ...reference, metadata }, deduped);
  const deterministic = acceptedCandidate(scored);
  if (deterministic) {
    return resolvedResult(type, deterministic.value, {
      source: deterministic.sources?.[0] ?? deterministic.source,
      confidence: Math.max(0.5, Math.min(1, deterministic.score / 100)),
      llmUsed: false,
      candidates: scored,
      errors,
      rationale: "Deterministic identifier candidate exceeded acceptance threshold.",
      version: deterministic.version ?? null,
    });
  }

  if (useLlm) {
    const llmDecision = await llmAdjudicator(reference, type, scored.slice(0, 6), {
      model: openaiModel,
      reasoningEffort: openaiReasoningEffort,
      openaiApiKey,
    });
    if (llmDecision && scored.some((candidate) => candidate.value === llmDecision.value) && llmDecision.confidence >= 0.65) {
      return resolvedResult(type, llmDecision.value, {
        source: "llm_adjudication",
        confidence: Math.min(1, llmDecision.confidence),
        llmUsed: true,
        candidates: scored,
        errors,
        rationale: llmDecision.rationale,
        llm: {
          model: llmDecision.model,
          reasoningEffort: llmDecision.reasoningEffort,
        },
      });
    }
  }

  return {
    status: "unresolved",
    type,
    value: null,
    doi: null,
    source: null,
    confidence: 0,
    llmUsed: false,
    candidates: scored,
    errors,
    rationale: scored.length ? "Candidates found but none met acceptance threshold." : "No identifier candidates were found.",
  };
}

function resolvedResult(type, value, extras) {
  return {
    status: "resolved",
    type,
    value,
    doi: type === "doi" ? value : undefined,
    arxiv_id: type === "arxiv_id" ? value : undefined,
    isbn13: type === "isbn13" ? value : undefined,
    publisher_item: type === "publisher_item" ? value : undefined,
    ...extras,
  };
}

async function resolveDoiForReference(options) {
  return resolveIdentifierForReference({ ...options, type: "doi" });
}

module.exports = {
  IDENTIFIER_TYPE_CONFIG,
  IDENTIFIER_TYPES,
  extractArxivId,
  extractArxivVersion,
  extractDoiFromText,
  hashShort,
  identifierNodeKey,
  identifiersFromObject,
  normalizeArxivId,
  normalizeDoi,
  normalizeIdentifier,
  normalizeIdentifierTypes,
  normalizeIsbn13,
  normalizePublisherItem,
  parseCatalogItems,
  resolveDoiForReference,
  resolveIdentifierForReference,
  sidecarDoi,
  sidecarIdentifier,
};
