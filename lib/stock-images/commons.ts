import { allowedLicence } from "./licences";
import { SourceBusy, SourceFailure, type SearchInput, type SearchResult, type StockCandidate, type StockImageSource } from "./types";

/**
 * Wikimedia Commons as an image source. No key is needed. What Wikimedia's documents require, and what this does about it:
 *
 * - User-Agent policy: every request names the client, a version and contact information (`PAPYRUS_WIKIMEDIA_CONTACT`, a web address or an
 *   address kept in the site's configuration, not in the repository). No browser or library default.
 * - API etiquette: requests go one at a time, spaced apart (`MINIMUM_GAP_MILLISECONDS`); `maxlag=5` so the API can tell us to wait; gzip is
 *   negotiated by the HTTP client; a 429, 503 or `maxlag` answer stops the search and tells the editor to try later instead of retrying in a loop.
 *   Results of a search are kept for ten minutes so a reload of the same page asks nothing.
 * - Licensing: the licence, creator and file page come from the API's structured `extmetadata`, per image. A file without them is dropped.
 */
export const COMMONS_API = "https://commons.wikimedia.org/w/api.php";
export const COMMONS_IMAGE_HOSTS = ["upload.wikimedia.org", "thumb.wikimedia.org"] as const;
export const SOURCE_ID = "wikimedia-commons";
export const SOURCE_LABEL = "Wikimedia Commons";
/** Standard Commons thumbnail size we ask for: wide enough for a cover, small enough to copy quickly. */
export const THUMBNAIL_WIDTH = 1280;
export const MINIMUM_WIDTH = 800;
export const ALLOWED_MIME_TYPES = ["image/jpeg", "image/png", "image/webp"];
export const MINIMUM_GAP_MILLISECONDS = 250;
const PAGE_SIZE = 20;
/** One click does at most this many search requests, one after another, to find four allowed images. A real latency bound, not a quota. */
const MAXIMUM_REQUESTS_PER_CLICK = 3;
const CACHE_MILLISECONDS = 10 * 60 * 1000;
const CACHE_ENTRIES = 100;
const MAXIMUM_TARGET_CHARACTERS = 120;
const EXTMETADATA_FILTER = "LicenseShortName|LicenseUrl|Artist|Copyrighted|NonFree|Restrictions|ObjectName|ImageDescription";

export type Fetcher = (url: string, init: { headers: Record<string, string> }) => Promise<Response>;

export type CommonsOptions = {
  fetcher?: Fetcher;
  contact?: string;
  sleep?: (milliseconds: number) => Promise<void>;
  now?: () => number;
};

export function userAgent(contact?: string): string {
  const where = (contact ?? "").trim() || "https://github.com/AnthusAI/Papyrus";
  return `PapyrusNewsroomImagePicker/1.0 (${where}) fetch`;
}

export function cleanTarget(value: string): string {
  return value.replace(/[^\p{L}\p{N}\s'-]+/gu, " ").replace(/\s+/g, " ").trim().slice(0, MAXIMUM_TARGET_CHARACTERS);
}

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

/** Text of an HTML fragment the API returns (creator names arrive as links): tags removed, entities decoded, whitespace collapsed. */
export function plainText(html: string): string {
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (whole, code: string) => {
      if (code[0] === "#") {
        const point = code[1].toLowerCase() === "x" ? Number.parseInt(code.slice(2), 16) : Number.parseInt(code.slice(1), 10);
        return Number.isFinite(point) && point > 0 && point < 0x110000 ? String.fromCodePoint(point) : " ";
      }
      return ENTITIES[code.toLowerCase()] ?? whole;
    })
    .replace(/\s+/g, " ")
    .trim();
}

type Extmetadata = Record<string, { value?: unknown } | undefined>;
type ImageInfo = {
  width?: number;
  height?: number;
  thumburl?: string;
  thumbwidth?: number;
  thumbheight?: number;
  url?: string;
  descriptionurl?: string;
  mime?: string;
  extmetadata?: Extmetadata;
};
export type CommonsPage = { title?: string; index?: number; missing?: boolean; imageinfo?: ImageInfo[] };

function metadata(meta: Extmetadata | undefined, key: string): string | null {
  const value = meta?.[key]?.value;
  return typeof value === "string" && value.trim() ? value : value === undefined || value === null ? null : String(value);
}

function truthy(value: string | null): boolean {
  return value !== null && /^(true|1|yes)$/i.test(value.trim());
}

function secureUrl(value: unknown, hosts: readonly string[]): string | null {
  if (typeof value !== "string") return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password) return null;
    return hosts.includes(parsed.hostname) ? parsed.toString() : null;
  } catch {
    return null;
  }
}

/** One API page as a candidate, or null with the reason it was dropped. Pure: tested on recorded answers. */
export function candidateFromPage(page: CommonsPage): { candidate: StockCandidate } | { dropped: string } {
  const info = page.imageinfo?.[0];
  if (!page.title || page.missing || !info) return { dropped: "no image information" };
  const meta = info.extmetadata;
  if (!meta) return { dropped: "no licence metadata" };
  if (!ALLOWED_MIME_TYPES.includes(info.mime ?? "")) return { dropped: `type ${info.mime ?? "unknown"} is not offered` };
  if (truthy(metadata(meta, "NonFree"))) return { dropped: "non-free" };
  if (metadata(meta, "Restrictions")) return { dropped: "has usage restrictions" };
  const licence = allowedLicence({ shortName: metadata(meta, "LicenseShortName"), url: metadata(meta, "LicenseUrl"), copyrighted: metadata(meta, "Copyrighted") });
  if (!licence) return { dropped: `licence ${metadata(meta, "LicenseShortName") ?? "unknown"} is not offered` };
  const creator = plainText(metadata(meta, "Artist") ?? "").slice(0, 200);
  if (!creator || /^(unknown|anonymous|n\/a|none)\b/i.test(creator)) return { dropped: "no known creator" };
  const sourceUrl = secureUrl(info.descriptionurl, ["commons.wikimedia.org"]);
  if (!sourceUrl) return { dropped: "no file page" };
  const original = typeof info.width === "number" && typeof info.height === "number" && info.width > 0 && info.height > 0;
  if (!original) return { dropped: "no size" };
  const scaled = typeof info.thumbwidth === "number" && typeof info.thumbheight === "number" && info.thumbwidth < (info.width as number);
  const width = scaled ? (info.thumbwidth as number) : (info.width as number);
  const height = scaled ? (info.thumbheight as number) : (info.height as number);
  if (width < MINIMUM_WIDTH) return { dropped: `only ${width} px wide` };
  const imageUrl = secureUrl(scaled ? info.thumburl : info.url, COMMONS_IMAGE_HOSTS);
  if (!imageUrl) return { dropped: "no usable picture address" };
  const fileName = page.title.replace(/^File:/, "").replace(/\.[A-Za-z0-9]+$/, "").replace(/_/g, " ");
  const title = plainText(metadata(meta, "ObjectName") ?? "").slice(0, 160) || fileName;
  const description = plainText(metadata(meta, "ImageDescription") ?? "").slice(0, 200);
  return {
    candidate: { id: page.title, source: SOURCE_ID, sourceLabel: SOURCE_LABEL, title, description, creator, licence, sourceUrl, imageUrl, width, height },
  };
}

class Queue {
  private tail: Promise<unknown> = Promise.resolve();
  private last = 0;
  constructor(private readonly gap: number, private readonly sleep: (milliseconds: number) => Promise<void>, private readonly now: () => number) {}
  /** Runs jobs strictly one after another with at least `gap` milliseconds between starts. */
  run<T>(job: () => Promise<T>): Promise<T> {
    const result = this.tail.then(async () => {
      const wait = this.last + this.gap - this.now();
      if (wait > 0) await this.sleep(wait);
      try {
        return await job();
      } finally {
        this.last = this.now();
      }
    });
    this.tail = result.catch(() => undefined);
    return result;
  }
}

const sharedQueue = new Queue(MINIMUM_GAP_MILLISECONDS, (ms) => new Promise((resolve) => setTimeout(resolve, ms)), () => Date.now());

export function createCommonsSource(options: CommonsOptions = {}): StockImageSource {
  const fetcher: Fetcher = options.fetcher ?? ((url, init) => fetch(url, { ...init, cache: "no-store" }));
  const now = options.now ?? (() => Date.now());
  const queue = options.sleep || options.now ? new Queue(MINIMUM_GAP_MILLISECONDS, options.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms))), now) : sharedQueue;
  const headers = { "user-agent": userAgent(options.contact ?? process.env.PAPYRUS_WIKIMEDIA_CONTACT), accept: "application/json", "accept-encoding": "gzip" };
  const cache = new Map<string, { at: number; pages: CommonsPage[]; next: number | null }>();

  async function call(parameters: Record<string, string>): Promise<{ pages: CommonsPage[]; next: number | null }> {
    const query = new URLSearchParams({
      action: "query", format: "json", formatversion: "2", prop: "imageinfo", maxlag: "5",
      iiprop: "url|size|mime|extmetadata", iiurlwidth: String(THUMBNAIL_WIDTH), iiextmetadatafilter: EXTMETADATA_FILTER, ...parameters,
    });
    const url = `${COMMONS_API}?${query.toString()}`;
    const cached = cache.get(url);
    if (cached && now() - cached.at < CACHE_MILLISECONDS) return cached;
    const response = await queue.run(async () => {
      try {
        return await fetcher(url, { headers });
      } catch (error) {
        throw new SourceFailure(`Wikimedia Commons could not be reached (${error instanceof Error ? error.message.slice(0, 80) : "network error"}).`);
      }
    });
    if (response.status === 429 || response.status === 503) {
      const retry = Number.parseInt(response.headers.get("retry-after") ?? "", 10);
      throw new SourceBusy(Number.isFinite(retry) ? retry : null);
    }
    if (!response.ok) throw new SourceFailure(`Wikimedia Commons answered ${response.status}.`);
    let body: { error?: { code?: string }; query?: { pages?: CommonsPage[] }; continue?: { gsroffset?: number } };
    try {
      body = await response.json();
    } catch {
      throw new SourceFailure("Wikimedia Commons answered something that was not JSON.");
    }
    if (body.error?.code === "maxlag" || body.error?.code === "ratelimited") throw new SourceBusy(null);
    if (body.error) throw new SourceFailure(`Wikimedia Commons refused the search (${String(body.error.code ?? "error").slice(0, 40)}).`);
    const pages = [...(body.query?.pages ?? [])].sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
    const entry = { at: now(), pages, next: typeof body.continue?.gsroffset === "number" ? body.continue.gsroffset : null };
    if (cache.size >= CACHE_ENTRIES) cache.delete(cache.keys().next().value as string);
    cache.set(url, entry);
    return entry;
  }

  return {
    id: SOURCE_ID,
    label: SOURCE_LABEL,
    imageHosts: COMMONS_IMAGE_HOSTS,

    async search({ target, cursor, exclude, count }: SearchInput): Promise<SearchResult> {
      const words = cleanTarget(target);
      if (!words) return { candidates: [], nextCursor: null };
      let offset = /^\d{1,6}$/.test(cursor) ? Number.parseInt(cursor, 10) : 0;
      const found: StockCandidate[] = [];
      let exhausted = false;
      for (let request = 0; request < MAXIMUM_REQUESTS_PER_CLICK && found.length < count && !exhausted; request += 1) {
        const { pages, next } = await call({
          generator: "search", gsrnamespace: "6", gsrsearch: `${words} filetype:bitmap`, gsrlimit: String(PAGE_SIZE), gsroffset: String(offset),
        });
        let consumed = 0;
        for (const page of pages) {
          consumed += 1;
          const result = candidateFromPage(page);
          if ("candidate" in result && !exclude.has(result.candidate.id) && !found.some((one) => one.id === result.candidate.id)) {
            found.push(result.candidate);
            if (found.length === count) break;
          }
        }
        if (found.length === count && consumed < pages.length) {
          offset += consumed;
          return { candidates: found, nextCursor: String(offset) };
        }
        if (next === null) exhausted = true;
        else offset = next;
      }
      return { candidates: found, nextCursor: exhausted ? null : String(offset) };
    },

    async lookup(id: string): Promise<StockCandidate | null> {
      if (!/^File:[^|<>{}[\]\n]{1,240}$/.test(id)) return null;
      const { pages } = await call({ titles: id });
      const result = pages[0] ? candidateFromPage(pages[0]) : null;
      return result && "candidate" in result ? result.candidate : null;
    },
  };
}
