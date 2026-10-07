import { toInternalReaderPath, toPublicReaderPath } from "./reader-base-path";
import { PAPYRUS_OBJECT_KINDS, type PapyrusObjectKind } from "./papyrus-object-kinds";
import {
  buildNewsroomIndexWebPath,
  effectiveAssignmentsIndexFilters,
  effectiveInsightsIndexFilters,
  effectiveMessagesIndexFilters,
  effectiveReferencesIndexFilters,
  normalizeReferenceIndexOrder,
  type AssignmentsIndexFilters,
  type InsightsIndexFilters,
  type MessagesIndexFilters,
  type NewsroomIndexTab,
  type ReferencesIndexFilters,
} from "./newsroom-index-filters";

export type PapyrusWebUiContext = {
  webPath: string;
  papyrusLocationUri: string;
  papyrusObjectUri?: string | null;
  newsroomTab?: string | null;
  viewMode?: "index" | "detail" | null;
  indexFilters?: Record<string, string> | null;
  label?: string | null;
};

const NEWSROOM_TAB_IDS = new Set([
  "overview",
  "messages",
  "insights",
  "assignments",
  "references",
  "topics",
  "concepts",
  "administration",
  "search",
  "sections",
]);

export function buildWebUiContext(webPath: string): PapyrusWebUiContext {
  const location = webPathToPapyrusLocation(webPath);
  return {
    webPath: location.webPath,
    papyrusLocationUri: location.papyrusLocationUri,
    papyrusObjectUri: location.papyrusObjectUri ?? null,
    newsroomTab: location.newsroomTab ?? null,
    viewMode: location.viewMode ?? null,
    indexFilters: location.indexFilters ?? null,
    label: location.label ?? null,
  };
}

export function webPathToPapyrusLocation(webPath: string): PapyrusWebUiContext {
  const normalized = normalizeWebPath(webPath);
  const url = new URL(normalized, "https://papyrus.local");
  const pathname = toInternalReaderPath(url.pathname || "/");

  if (pathname === "/" || pathname === "") {
    return location("papyrus://site/home", normalized, { label: "Papyrus home" });
  }
  if (pathname === "/archive") {
    return location("papyrus://site/archive", normalized, { label: "Archive" });
  }
  if (pathname === "/settings") {
    return location("papyrus://site/settings", normalized, { label: "Settings" });
  }
  if (pathname.startsWith("/articles/")) {
    const slug = decodeURIComponent(pathname.slice("/articles/".length).replace(/\/+$/, ""));
    if (slug) {
      const objectUri = `papyrus://item/${encodeURIComponent(slug)}`;
      return location(objectUri, normalized, { papyrusObjectUri: objectUri, label: `Article ${slug}` });
    }
  }

  const editionArticle = matchEditionArticlePath(pathname);
  if (editionArticle) {
    const objectUri = `papyrus://item/${encodeURIComponent(editionArticle.slug)}`;
    return location(objectUri, normalized, {
      papyrusObjectUri: objectUri,
      label: `Edition article ${editionArticle.year}-${editionArticle.month}-${editionArticle.day} / ${editionArticle.slug}`,
    });
  }

  if (!pathname.startsWith("/newsroom")) {
    const tail = (url.pathname || "/").replace(/^\/+/, "");
    return location(`papyrus://site/path/${encodeURIComponent(tail)}`, normalized, { label: pathname });
  }

  if (pathname === "/newsroom" || pathname === "/newsroom/") {
    return location("papyrus://newsroom/overview", normalized, { newsroomTab: "overview", label: "Newsroom overview" });
  }

  const segments = pathname.split("/").filter(Boolean);
  const tab = segments[1] ?? "overview";

  if (tab === "sections" && segments[2]) {
    const sectionId = decodeURIComponent(segments[2]);
    const objectUri = `papyrus://newsroomSection/${encodeURIComponent(sectionId)}`;
    return location(objectUri, normalized, {
      papyrusObjectUri: objectUri,
      newsroomTab: "sections",
      label: `Newsroom section ${sectionId}`,
    });
  }

  if (tab === "search") {
    const anchorUri = searchAnchorUri(url.searchParams);
    const locationUri = anchorUri
      ? `papyrus://newsroom/search/${anchorUri.replace(/^papyrus:\/\//, "")}`
      : "papyrus://newsroom/search";
    return location(locationUri, normalized, {
      papyrusObjectUri: anchorUri,
      newsroomTab: "search",
      label: "Newsroom search",
    });
  }

  if (tab === "administration") {
    const panel = segments.slice(2).join("/") || "overview";
    return location(`papyrus://newsroom/administration/${encodeURIComponent(panel)}`, normalized, {
      newsroomTab: "administration",
      label: `Newsroom administration / ${panel}`,
    });
  }

  if ((tab === "references" || tab === "messages" || tab === "assignments" || tab === "insights") && segments.length === 2) {
    return newsroomIndexLocation(tab as NewsroomIndexTab, normalized, url.searchParams);
  }

  if (tab === "insights" && segments[2]) {
    const threadId = decodeURIComponent(segments[2]);
    const objectUri = `papyrus://message/${encodeURIComponent(threadId)}`;
    return location(objectUri, normalized, {
      papyrusObjectUri: objectUri,
      newsroomTab: "insights",
      viewMode: "detail",
      label: `Insight thread ${threadId}`,
    });
  }

  if ((tab === "references" || tab === "messages" || tab === "assignments") && segments[2]) {
    const objectId = decodeURIComponent(segments[2]);
    const kind = tab === "references" ? "reference" : tab === "messages" ? "message" : "assignment";
    const objectUri = `papyrus://${kind}/${encodeURIComponent(objectId)}`;
    return location(objectUri, normalized, {
      papyrusObjectUri: objectUri,
      newsroomTab: tab,
      viewMode: "detail",
      label: `${kind} ${objectId}`,
    });
  }

  if (tab === "topics") {
    const category = url.searchParams.get("category")?.trim();
    if (category) {
      const objectUri = `papyrus://category/${encodeURIComponent(category)}`;
      return location(objectUri, normalized, {
        papyrusObjectUri: objectUri,
        newsroomTab: "topics",
        label: `Category ${category}`,
      });
    }
    return location("papyrus://newsroom/topics", normalized, { newsroomTab: "topics", label: "Newsroom topics" });
  }

  if (tab === "concepts") {
    const node = url.searchParams.get("node")?.trim();
    if (node) {
      const objectUri = `papyrus://semanticNode/${encodeURIComponent(node)}`;
      return location(objectUri, normalized, {
        papyrusObjectUri: objectUri,
        newsroomTab: "concepts",
        label: `Semantic node ${node}`,
      });
    }
    const category = url.searchParams.get("category")?.trim();
    if (category) {
      const objectUri = `papyrus://category/${encodeURIComponent(category)}`;
      return location(objectUri, normalized, {
        papyrusObjectUri: objectUri,
        newsroomTab: "concepts",
        label: `Category ${category}`,
      });
    }
    return location("papyrus://newsroom/concepts", normalized, { newsroomTab: "concepts", label: "Newsroom concepts" });
  }

  if (NEWSROOM_TAB_IDS.has(tab)) {
    return location(`papyrus://newsroom/${encodeURIComponent(tab)}`, normalized, {
      newsroomTab: tab,
      label: `Newsroom ${tab}`,
    });
  }

  const remainder = segments.slice(1).join("/");
  return location(`papyrus://newsroom/${encodeURIComponent(remainder)}`, normalized, {
    newsroomTab: tab,
    label: `Newsroom ${remainder}`,
  });
}

export type PapyrusUriToWebPathResult = {
  ok: true;
  webPath: string;
  papyrusLocationUri: string;
  papyrusObjectUri?: string;
  viewMode?: "index" | "detail";
  indexFilters?: Record<string, string>;
};

export function papyrusUriToWebPath(uri: string): PapyrusUriToWebPathResult {
  const raw = uri.trim();
  if (!raw) throw new Error("Papyrus location URI is required");

  const parsed = parsePapyrusUri(raw);
  const { kind, id } = parsed;

  if (kind === "site") {
    if (id === "home") return { ok: true, papyrusLocationUri: raw, webPath: toPublicReaderPath("/") };
    if (id === "archive") return { ok: true, papyrusLocationUri: raw, webPath: toPublicReaderPath("/archive") };
    if (id === "settings") return { ok: true, papyrusLocationUri: raw, webPath: toPublicReaderPath("/settings") };
    if (id.startsWith("path/")) {
      return { ok: true, papyrusLocationUri: raw, webPath: `/${decodeURIComponent(id.slice("path/".length))}` };
    }
    throw new Error(`Unsupported site location URI: ${raw}`);
  }

  if (PAPYRUS_OBJECT_KINDS.has(kind as PapyrusObjectKind)) {
    const webPath = objectKindToWebPath(kind as PapyrusObjectKind, id);
    return { ok: true, papyrusLocationUri: raw, papyrusObjectUri: raw, webPath };
  }

  if (kind !== "newsroom") {
    throw new Error(`Unsupported Papyrus location URI kind: ${kind}`);
  }

  if (id === "overview") return { ok: true, papyrusLocationUri: raw, webPath: "/newsroom" };
  if (id === "assignments/budget") {
    return {
      ok: true,
      papyrusLocationUri: raw,
      webPath: "/newsroom/assignments?view=budget",
      viewMode: "index",
      indexFilters: { view: "budget" },
    };
  }

  const indexMapped = newsroomIndexUriToWebPath(raw, id);
  if (indexMapped) return indexMapped;

  if (id === "search") return { ok: true, papyrusLocationUri: raw, webPath: "/newsroom/search" };

  if (id.startsWith("search/")) {
    const anchorTail = id.slice("search/".length);
    const slash = anchorTail.indexOf("/");
    if (slash < 0) throw new Error(`Invalid anchored search location URI: ${raw}`);
    const anchorKind = canonicalObjectKind(anchorTail.slice(0, slash));
    const anchorId = decodeURIComponent(anchorTail.slice(slash + 1));
    if (!anchorKind) throw new Error(`Invalid anchored search location URI: ${raw}`);
    const params = new URLSearchParams({
      anchorKind,
      anchorId,
      anchorLineageId: anchorId,
    });
    const objectUri = `papyrus://${anchorKind}/${encodeURIComponent(anchorId)}`;
    return {
      ok: true,
      papyrusLocationUri: raw,
      papyrusObjectUri: objectUri,
      webPath: `/newsroom/search?${params.toString()}`,
    };
  }

  if (id.startsWith("administration/")) {
    const panel = decodeURIComponent(id.slice("administration/".length));
    return { ok: true, papyrusLocationUri: raw, webPath: `/newsroom/administration/${panel}` };
  }

  if (NEWSROOM_TAB_IDS.has(id)) {
    if (id === "references" || id === "messages" || id === "assignments" || id === "insights") {
      const mapped = newsroomIndexUriToWebPath(raw, `${id}/index`);
      if (mapped) return mapped;
    }
    return { ok: true, papyrusLocationUri: raw, webPath: id === "overview" ? "/newsroom" : `/newsroom/${id}` };
  }

  if (id.includes("/")) {
    return { ok: true, papyrusLocationUri: raw, webPath: `/newsroom/${decodeURIComponent(id)}` };
  }

  throw new Error(`Unsupported newsroom location URI: ${raw}`);
}

export function extractNavigationIntent(toolResultJson: unknown): { webPath: string; papyrusLocationUri: string } | null {
  if (!toolResultJson || typeof toolResultJson !== "object" || Array.isArray(toolResultJson)) return null;
  const envelope = toolResultJson as Record<string, unknown>;
  if (envelope.ok !== true) return null;
  const value = envelope.value;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const navigation = (value as Record<string, unknown>).navigation;
  if (!navigation || typeof navigation !== "object" || Array.isArray(navigation)) return null;
  const webPath = (navigation as Record<string, unknown>).webPath;
  const papyrusLocationUri = (navigation as Record<string, unknown>).papyrusLocationUri;
  if (typeof webPath !== "string" || !webPath.trim()) return null;
  if (typeof papyrusLocationUri !== "string" || !papyrusLocationUri.trim()) return null;
  return { webPath: webPath.trim(), papyrusLocationUri: papyrusLocationUri.trim() };
}

function location(
  papyrusLocationUri: string,
  webPath: string,
  extras?: Partial<PapyrusWebUiContext>,
): PapyrusWebUiContext {
  return {
    webPath,
    papyrusLocationUri,
    papyrusObjectUri: extras?.papyrusObjectUri ?? null,
    newsroomTab: extras?.newsroomTab ?? null,
    viewMode: extras?.viewMode ?? null,
    indexFilters: extras?.indexFilters ?? null,
    label: extras?.label ?? null,
  };
}

function newsroomIndexLocation(tab: NewsroomIndexTab, webPath: string, searchParams: URLSearchParams): PapyrusWebUiContext {
  const filters = readIndexFiltersFromSearchParams(tab, searchParams);
  const locationUri = buildNewsroomIndexLocationUri(tab, filters);
  const label = [`Newsroom ${tab} index`, ...Object.entries(filters).filter(([, value]) => value).map(([key, value]) => `${key}=${value}`)].join(" ");
  return location(locationUri, webPath, {
    newsroomTab: tab,
    viewMode: "index",
    indexFilters: filters,
    label,
  });
}

function readIndexFiltersFromSearchParams(tab: NewsroomIndexTab, searchParams: URLSearchParams): Record<string, string> {
  if (tab === "references") {
    const orderParam = searchParams.get("order")?.trim();
    return effectiveReferencesIndexFilters({
      status: searchParams.get("status")?.trim() || undefined,
      processing: searchParams.get("processing")?.trim() ?? undefined,
      order: orderParam ? normalizeReferenceIndexOrder(orderParam) : undefined,
    });
  }
  if (tab === "messages") return effectiveMessagesIndexFilters({
    kind: searchParams.get("kind")?.trim() ?? undefined,
    domain: searchParams.get("domain")?.trim() ?? undefined,
  });
  if (tab === "insights") return effectiveInsightsIndexFilters({
    domain: searchParams.get("domain")?.trim() ?? undefined,
  });
  return effectiveAssignmentsIndexFilters({
    status: searchParams.get("status")?.trim() ?? undefined,
    type: searchParams.get("type")?.trim() ?? undefined,
    view: searchParams.get("view")?.trim() ?? undefined,
  });
}

function buildNewsroomIndexLocationUri(tab: NewsroomIndexTab, filters: Record<string, string>): string {
  const segments = [tab, "index"];
  if (tab === "references") {
    const normalized = filters as ReferencesIndexFilters;
    if (normalized.status && normalized.status !== "exclude-pending") segments.push("status", normalized.status);
    if (normalized.processing?.trim()) segments.push("processing", normalized.processing.trim());
    if (normalized.order === "imported") segments.push("order", "imported");
  } else if (tab === "messages") {
    const normalized = filters as MessagesIndexFilters;
    if (normalized.kind?.trim()) segments.push("kind", normalized.kind.trim());
    if (normalized.domain?.trim()) segments.push("domain", normalized.domain.trim());
  } else if (tab === "insights") {
    const normalized = filters as InsightsIndexFilters;
    if (normalized.domain?.trim()) segments.push("domain", normalized.domain.trim());
  } else {
    const normalized = filters as AssignmentsIndexFilters;
    if (normalized.status?.trim()) segments.push("status", normalized.status.trim());
    if (normalized.type?.trim()) segments.push("type", normalized.type.trim());
    if (normalized.view === "budget") segments.push("view", "budget");
  }
  return `papyrus://newsroom/${segments.map((segment) => encodeURIComponent(segment)).join("/")}`;
}

function newsroomIndexUriToWebPath(
  papyrusLocationUri: string,
  objectId: string,
): { ok: true; webPath: string; papyrusLocationUri: string; viewMode: "index"; indexFilters: Record<string, string> } | null {
  const parsed = parseIndexUriTail(objectId);
  if (!parsed) return null;
  const { tab, filters } = parsed;
  return {
    ok: true,
    papyrusLocationUri,
    webPath: buildNewsroomIndexWebPath(tab, filters as ReferencesIndexFilters & MessagesIndexFilters & AssignmentsIndexFilters),
    viewMode: "index",
    indexFilters: filters,
  };
}

function parseIndexUriTail(objectId: string): { tab: NewsroomIndexTab; filters: Record<string, string> } | null {
  const segments = objectId.split("/").filter(Boolean);
  if (!segments.length) return null;
  const tab = segments[0];
  if (tab !== "references" && tab !== "messages" && tab !== "assignments" && tab !== "insights") return null;
  if (segments.length === 1) {
    return { tab, filters: readIndexFiltersFromSearchParams(tab, new URLSearchParams()) };
  }
  if (segments[1] === "budget" && tab === "assignments") {
    return { tab, filters: effectiveAssignmentsIndexFilters({ view: "budget" }) };
  }
  if (segments[1] !== "index") return null;
  const filters: Record<string, string> = {};
  for (let index = 2; index + 1 < segments.length; index += 2) {
    filters[segments[index]] = decodeURIComponent(segments[index + 1]);
  }
  if (tab === "references") return { tab, filters: effectiveReferencesIndexFilters(filters) };
  if (tab === "messages") return { tab, filters: effectiveMessagesIndexFilters(filters) };
  if (tab === "insights") return { tab, filters: effectiveInsightsIndexFilters(filters) };
  return { tab, filters: effectiveAssignmentsIndexFilters(filters) };
}

function normalizeWebPath(webPath: string): string {
  const raw = webPath.trim();
  if (!raw) return "/newsroom";
  if (raw.startsWith("http://") || raw.startsWith("https://")) return raw;
  const queryIndex = raw.indexOf("?");
  if (queryIndex >= 0) return raw;
  return raw;
}

function matchEditionArticlePath(pathname: string): { year: string; month: string; day: string; slug: string } | null {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length !== 4) return null;
  const [year, month, day, slug] = segments;
  if (!/^\d+$/.test(year) || !/^\d+$/.test(month) || !/^\d+$/.test(day)) return null;
  return { year, month, day, slug: decodeURIComponent(slug) };
}

function searchAnchorUri(searchParams: URLSearchParams): string | null {
  const anchorKind = canonicalObjectKind(searchParams.get("anchorKind") ?? "");
  const anchorId = searchParams.get("anchorId")?.trim() ?? "";
  if (!anchorKind || !anchorId) return null;
  return `papyrus://${anchorKind}/${encodeURIComponent(anchorId)}`;
}

function objectKindToWebPath(kind: PapyrusObjectKind, objectId: string): string {
  const encoded = encodeURIComponent(decodeURIComponent(objectId));
  if (kind === "reference") return `/newsroom/references/${encoded}`;
  if (kind === "message") return `/newsroom/messages/${encoded}`;
  if (kind === "assignment") return `/newsroom/assignments/${encoded}`;
  if (kind === "category") return `/newsroom/topics?category=${encoded}`;
  if (kind === "semanticNode") return `/newsroom/concepts?node=${encoded}`;
  if (kind === "newsroomSection") return `/newsroom/sections/${encoded}`;
  if (kind === "item") return toPublicReaderPath(`/articles/${encoded}`);
  return `/newsroom?object=${encodeURIComponent(kind)}:${encoded}`;
}

function parsePapyrusUri(uri: string): { kind: string; id: string } {
  const parsed = new URL(uri);
  if (parsed.protocol !== "papyrus:") throw new Error(`Papyrus URI must use papyrus:// scheme: ${uri}`);
  if (parsed.search || parsed.hash) throw new Error(`Papyrus URI must not include query or fragment: ${uri}`);
  const kind = canonicalObjectKind(decodeURIComponent(parsed.hostname));
  const id = decodeURIComponent(parsed.pathname.replace(/^\/+/, ""));
  if (!kind) throw new Error(`Papyrus URI kind is required: ${uri}`);
  if (!id) throw new Error(`Papyrus URI object id is required: ${uri}`);
  return { kind, id };
}

function canonicalObjectKind(kind: string): string | null {
  const trimmed = kind.trim();
  if (!trimmed) return null;
  if (trimmed === "newsroom" || trimmed === "site") return trimmed;
  if (PAPYRUS_OBJECT_KINDS.has(trimmed as PapyrusObjectKind)) return trimmed;
  const lowered = trimmed.toLowerCase();
  for (const candidate of PAPYRUS_OBJECT_KINDS) {
    if (candidate.toLowerCase() === lowered) return candidate;
  }
  if (lowered === "newsroomsection") return "newsroomSection";
  if (lowered === "semanticnode") return "semanticNode";
  if (lowered === "categoryset") return "categorySet";
  return null;
}
