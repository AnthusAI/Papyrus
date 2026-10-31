/**
 * The public story source: what an anonymous visitor reads from the site's own S3 projection under its public origin.
 *
 * Why this path and not the guest `PublishedItem` GraphQL model (docs/alexa.md lists both):
 *  - The skill function has no AppSync credentials. `PublishedItem` allows `allow.guest()` (the identity pool's unauthenticated
 *    role) and the content-write groups; the site API's authorization modes are user pool (default) and API key, and the model
 *    has no API key rule. A Lambda role is none of those callers, so reading it would need a schema change (`allow.resource`)
 *    or unauthenticated Cognito identity credentials plus SigV4 signing, both outside this plugin.
 *  - The projection needs no secret and no IAM: `_data/latest.json` lists the newest pages and each page has a `.md` twin that carries
 *    the story's facts and its Markus source verbatim. `content/markus-source.ts` reads that source into the same `MarkusDocument`
 *    nodes `bodyIr` holds, so the speech still walks IR nodes, not text.
 *
 * Differences from the GraphQL shape, all visible in the types: `id` is the slug (the projection carries no row id), `publishedAt` is
 * the entry's date, and `bodyIr` is built from the source. Tenant scoping is already done by the projection (each site, and each
 * Prospectus tenant's site, has its own origin), so no `tenantId` is passed.
 */
import type { PublicStory, PublicStorySource, PublicStorySummary } from "../contracts";
import { parseMarkusSource } from "./markus-source";
import { splitTwin } from "./twin";

export const LATEST_PATH = "/_data/latest.json";
export const SEARCH_INDEX_PATH = "/_data/search-index.json";
const REQUEST_TIMEOUT_MS = 4000;

export type FetchLike = (url: string, init?: { signal?: AbortSignal; headers?: Record<string, string> }) => Promise<{
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
  text(): Promise<string>;
}>;

type Entry = { title: string; url: string; summary?: string; date?: string; authors?: string[]; publication?: string };

/** The slug of a page path: `/articles/x/` and `/articles/x.html` are both `articles/x`. Empty for the home page. */
export function slugOfPath(pathname: string): string {
  return pathname.replace(/^\/+|\/+$/g, "").replace(/\.(html|md)$/, "").replace(/\/index$/, "");
}

/** The Markdown twin's path for a page path (see the site's `md_key`). */
export function twinPath(pathname: string): string {
  if (pathname.endsWith("/")) return `${pathname}index.md`;
  if (pathname.endsWith(".html")) return `${pathname.slice(0, -".html".length)}.md`;
  return `${pathname}.md`;
}

function pathnameOf(url: string): string {
  // Only the path is used: a listing entry can never send the function to another host.
  try {
    return new URL(url, "https://site.invalid").pathname;
  } catch {
    return "";
  }
}

function isoDate(date: string | undefined): string {
  if (!date) return "";
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? `${date}T00:00:00Z` : date;
}

function summaryOf(entry: Entry): PublicStorySummary {
  const slug = slugOfPath(pathnameOf(entry.url));
  return {
    id: slug,
    slug,
    title: entry.title,
    ...(entry.summary ? { deck: entry.summary } : {}),
    ...(entry.authors && entry.authors.length > 0 ? { byline: entry.authors.join(", ") } : {}),
    publishedAt: isoDate(entry.date),
  };
}

export function createPublicSiteStorySource(options: { origin: string; fetch?: FetchLike }): PublicStorySource {
  const origin = options.origin.replace(/\/+$/, "");
  const get = options.fetch ?? (globalThis.fetch as unknown as FetchLike);

  async function request(path: string) {
    return get(`${origin}${path}`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS), headers: { accept: "application/json, text/markdown" } });
  }

  async function entries(path: string): Promise<Entry[]> {
    const response = await request(path);
    if (!response.ok) throw new Error(`The site's ${path} answered ${response.status}.`);
    const body = await response.json();
    if (!Array.isArray(body)) throw new Error(`The site's ${path} is not a list.`);
    return body.filter(
      (entry): entry is Entry => typeof entry === "object" && entry !== null && typeof entry.title === "string" && typeof entry.url === "string" && slugOfPath(pathnameOf(entry.url)) !== "",
    );
  }

  return {
    async listLatest({ limit }) {
      return (await entries(LATEST_PATH)).slice(0, Math.max(0, limit)).map(summaryOf);
    },

    async getStory(slug): Promise<PublicStory | undefined> {
      let entry = (await entries(LATEST_PATH)).find((candidate) => slugOfPath(pathnameOf(candidate.url)) === slug);
      if (entry === undefined) {
        const search = await request(SEARCH_INDEX_PATH);
        if (search.ok) {
          const listed = await search.json();
          if (Array.isArray(listed)) entry = (listed as Entry[]).find((candidate) => typeof candidate?.url === "string" && slugOfPath(pathnameOf(candidate.url)) === slug);
        }
      }
      if (entry === undefined) return undefined;

      const response = await request(twinPath(pathnameOf(entry.url)));
      if (response.status === 404) return undefined;
      if (!response.ok) throw new Error(`The story's Markdown twin answered ${response.status}.`);
      const twin = splitTwin(await response.text());
      const summary = summaryOf(entry);
      return {
        ...summary,
        ...(summary.deck === undefined && twin.summary ? { deck: twin.summary } : {}),
        ...(summary.byline === undefined && twin.byline ? { byline: twin.byline } : {}),
        markus: twin.body,
        bodyIr: parseMarkusSource(twin.body),
      };
    },
  };
}
