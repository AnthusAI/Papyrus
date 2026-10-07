import { getReaderBasePath, toPublicReaderPath } from "./reader-base-path";

const MONTH_NAMES = [
  "january",
  "february",
  "march",
  "april",
  "may",
  "june",
  "july",
  "august",
  "september",
  "october",
  "november",
  "december",
] as const;

type EditionDateRouteInput = {
  year: string;
  month: string;
  day: string;
};

type ParsedEditionDateRoute = {
  editionDate: string;
  canonicalPath: string;
  isCanonical: boolean;
};

type ParsedEditionPageRoute = ParsedEditionDateRoute & {
  pageNumber: number;
};

type ParsedEditionArticleRoute = ParsedEditionDateRoute & {
  articleSlug: string;
};

type ParsedEditionSectionRoute = ParsedEditionDateRoute & {
  sectionKey: string;
};

const RESERVED_DATE_CHILD_SEGMENTS = new Set(["page", "section"]);

export function getEditionDatePath(editionDate: string, readerBasePath: string = getReaderBasePath()): string {
  const match = editionDate.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return toPublicReaderPath("/", readerBasePath);

  const monthIndex = Number(match[2]) - 1;
  const monthName = MONTH_NAMES[monthIndex];
  if (!monthName) return toPublicReaderPath("/", readerBasePath);

  return toPublicReaderPath(`/${match[1]}/${monthName}/${match[3]}`, readerBasePath);
}

export function getEditionPagePath(editionDate: string, pageNumber: number, readerBasePath: string = getReaderBasePath()): string {
  const basePath = getEditionDatePath(editionDate, readerBasePath);
  return pageNumber <= 1 ? basePath : `${basePath}/page/${pageNumber}`;
}

export function getEditionSectionPath(editionDate: string, sectionKey: string, readerBasePath: string = getReaderBasePath()): string {
  return `${getEditionDatePath(editionDate, readerBasePath)}/section/${encodeURIComponent(sectionKey)}`;
}

export function getEditionArticlePath(editionDate: string, articleSlug: string, readerBasePath: string = getReaderBasePath()): string {
  return `${getEditionDatePath(editionDate, readerBasePath)}/${encodeURIComponent(articleSlug)}`;
}

export const getEditionItemPath = getEditionArticlePath;

export function parseEditionDateRoute(input: EditionDateRouteInput, readerBasePath: string = getReaderBasePath()): ParsedEditionDateRoute | null {
  const parsed = parseEditionDateSegments(input, readerBasePath);
  if (!parsed) return null;

  return {
    ...parsed,
    isCanonical: getCurrentDatePath(input, readerBasePath) === parsed.canonicalPath,
  };
}

export function parseEditionPageRoute(input: EditionDateRouteInput & { pageNumber: string }, readerBasePath: string = getReaderBasePath()): ParsedEditionPageRoute | null {
  const parsed = parseEditionDateSegments(input, readerBasePath);
  if (!parsed) return null;
  if (!/^\d+$/.test(input.pageNumber)) return null;

  const pageNumber = Number(input.pageNumber);
  if (!Number.isSafeInteger(pageNumber) || pageNumber < 1) return null;

  const canonicalPath = getEditionPagePath(parsed.editionDate, pageNumber, readerBasePath);
  const currentPath = `${getCurrentDatePath(input, readerBasePath)}/page/${input.pageNumber}`;
  return {
    editionDate: parsed.editionDate,
    canonicalPath,
    isCanonical: currentPath === canonicalPath,
    pageNumber,
  };
}

export function parseEditionArticleRoute(input: EditionDateRouteInput & { articleSlug: string }, readerBasePath: string = getReaderBasePath()): ParsedEditionArticleRoute | null {
  const parsed = parseEditionDateSegments(input, readerBasePath);
  if (!parsed) return null;
  if (RESERVED_DATE_CHILD_SEGMENTS.has(input.articleSlug.toLowerCase())) return null;

  const canonicalPath = getEditionArticlePath(parsed.editionDate, input.articleSlug, readerBasePath);
  const currentPath = `${getCurrentDatePath(input, readerBasePath)}/${input.articleSlug}`;
  return {
    editionDate: parsed.editionDate,
    canonicalPath,
    isCanonical: currentPath === canonicalPath,
    articleSlug: input.articleSlug,
  };
}

export function parseEditionSectionRoute(input: EditionDateRouteInput & { sectionKey: string }, readerBasePath: string = getReaderBasePath()): ParsedEditionSectionRoute | null {
  const parsed = parseEditionDateSegments(input, readerBasePath);
  if (!parsed) return null;
  if (!input.sectionKey.trim()) return null;

  const canonicalPath = getEditionSectionPath(parsed.editionDate, input.sectionKey, readerBasePath);
  const currentPath = `${getCurrentDatePath(input, readerBasePath)}/section/${input.sectionKey}`;
  return {
    editionDate: parsed.editionDate,
    canonicalPath,
    isCanonical: currentPath === canonicalPath,
    sectionKey: input.sectionKey,
  };
}

function parseEditionDateSegments(input: EditionDateRouteInput, readerBasePath: string): Omit<ParsedEditionDateRoute, "isCanonical"> | null {
  if (!/^\d{4}$/.test(input.year)) return null;

  const monthIndex = MONTH_NAMES.indexOf(input.month.toLowerCase() as (typeof MONTH_NAMES)[number]);
  if (monthIndex < 0) return null;

  if (!/^\d{1,2}$/.test(input.day)) return null;
  const dayNumber = Number(input.day);
  if (dayNumber < 1 || dayNumber > 31) return null;

  const monthNumber = monthIndex + 1;
  const canonicalDay = String(dayNumber).padStart(2, "0");
  const editionDate = `${input.year}-${String(monthNumber).padStart(2, "0")}-${canonicalDay}`;
  if (!isValidIsoDate(editionDate)) return null;

  return {
    editionDate,
    canonicalPath: getEditionDatePath(editionDate, readerBasePath),
  };
}

function getCurrentDatePath(input: EditionDateRouteInput, readerBasePath: string): string {
  return toPublicReaderPath(`/${input.year}/${input.month}/${input.day}`, readerBasePath);
}

function isValidIsoDate(editionDate: string): boolean {
  const [year, month, day] = editionDate.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}
