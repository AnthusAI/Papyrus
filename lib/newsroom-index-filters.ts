export type NewsroomIndexTab = "references" | "messages" | "assignments" | "insights";

export type ReferenceIndexOrder = "published" | "imported";

export type ReferencesIndexFilters = { status: string; processing: string; order: ReferenceIndexOrder };
export type MessagesIndexFilters = { kind: string; domain: string };
export type AssignmentsIndexFilters = { status: string; type: string; view: string };
export type InsightsIndexFilters = { domain: string };

export const DEFAULT_REFERENCES_INDEX_FILTERS: ReferencesIndexFilters = {
  status: "exclude-pending",
  processing: "",
  order: "published",
};

export const DEFAULT_MESSAGES_INDEX_FILTERS: MessagesIndexFilters = {
  kind: "",
  domain: "",
};

export const DEFAULT_ASSIGNMENTS_INDEX_FILTERS: AssignmentsIndexFilters = {
  status: "",
  type: "",
  view: "queue",
};

export const DEFAULT_INSIGHTS_INDEX_FILTERS: InsightsIndexFilters = {
  domain: "",
};

export function referencesStatusFromUrl(value: string): string {
  return value === "exclude-pending" ? "__exclude_pending" : value;
}

export function referencesStatusToUrl(value: string): string {
  return value === "__exclude_pending" ? "exclude-pending" : value;
}

export function normalizeReferenceIndexOrder(value: string | null | undefined): ReferenceIndexOrder {
  return value?.trim() === "imported" ? "imported" : "published";
}

export function effectiveReferencesIndexFilters(partial?: Partial<ReferencesIndexFilters>): ReferencesIndexFilters {
  const order = normalizeReferenceIndexOrder(partial?.order);
  const explicitStatus = partial?.status?.trim();
  let status = explicitStatus || DEFAULT_REFERENCES_INDEX_FILTERS.status;
  // Import-date sort is for intake triage; the default "reviewed only" filter hides
  // pending references created by inbound email and other intake paths.
  if (order === "imported" && !explicitStatus) {
    status = "";
  }
  return {
    status,
    processing: partial?.processing?.trim() ?? DEFAULT_REFERENCES_INDEX_FILTERS.processing,
    order,
  };
}

export function effectiveMessagesIndexFilters(partial?: Partial<MessagesIndexFilters>): MessagesIndexFilters {
  return {
    kind: partial?.kind?.trim() ?? DEFAULT_MESSAGES_INDEX_FILTERS.kind,
    domain: partial?.domain?.trim() ?? DEFAULT_MESSAGES_INDEX_FILTERS.domain,
  };
}

export function effectiveAssignmentsIndexFilters(partial?: Partial<AssignmentsIndexFilters>): AssignmentsIndexFilters {
  return {
    status: partial?.status?.trim() ?? DEFAULT_ASSIGNMENTS_INDEX_FILTERS.status,
    type: partial?.type?.trim() ?? DEFAULT_ASSIGNMENTS_INDEX_FILTERS.type,
    view: partial?.view?.trim() || DEFAULT_ASSIGNMENTS_INDEX_FILTERS.view,
  };
}

export function effectiveInsightsIndexFilters(partial?: Partial<InsightsIndexFilters>): InsightsIndexFilters {
  return {
    domain: partial?.domain?.trim() ?? DEFAULT_INSIGHTS_INDEX_FILTERS.domain,
  };
}

export function readReferencesIndexFilters(searchParams: URLSearchParams): ReferencesIndexFilters {
  const statusParam = searchParams.get("status")?.trim() ?? "";
  const orderParam = searchParams.get("order")?.trim();
  return effectiveReferencesIndexFilters({
    status: statusParam ? referencesStatusFromUrl(statusParam) : undefined,
    processing: searchParams.get("processing")?.trim() ?? undefined,
    order: orderParam ? normalizeReferenceIndexOrder(orderParam) : undefined,
  });
}

export function readMessagesIndexFilters(searchParams: URLSearchParams): MessagesIndexFilters {
  return effectiveMessagesIndexFilters({
    kind: searchParams.get("kind")?.trim() ?? undefined,
    domain: searchParams.get("domain")?.trim() ?? undefined,
  });
}

export function readAssignmentsIndexFilters(searchParams: URLSearchParams): AssignmentsIndexFilters {
  return effectiveAssignmentsIndexFilters({
    status: searchParams.get("status")?.trim() ?? undefined,
    type: searchParams.get("type")?.trim() ?? undefined,
    view: searchParams.get("view")?.trim() ?? undefined,
  });
}

export function readInsightsIndexFilters(searchParams: URLSearchParams): InsightsIndexFilters {
  return effectiveInsightsIndexFilters({
    domain: searchParams.get("domain")?.trim() ?? undefined,
  });
}

export function buildReferencesIndexQuery(filters: ReferencesIndexFilters): string {
  const params = new URLSearchParams();
  if (filters.status && filters.status !== DEFAULT_REFERENCES_INDEX_FILTERS.status) {
    params.set("status", referencesStatusToUrl(filters.status));
  }
  if (filters.processing.trim()) params.set("processing", filters.processing.trim());
  if (filters.order === "imported") params.set("order", "imported");
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function buildMessagesIndexQuery(filters: MessagesIndexFilters): string {
  const params = new URLSearchParams();
  if (filters.kind.trim()) params.set("kind", filters.kind.trim());
  if (filters.domain.trim()) params.set("domain", filters.domain.trim());
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function buildAssignmentsIndexQuery(filters: AssignmentsIndexFilters): string {
  const params = new URLSearchParams();
  if (filters.status.trim()) params.set("status", filters.status.trim());
  if (filters.type.trim()) params.set("type", filters.type.trim());
  if (filters.view.trim() === "budget") params.set("view", "budget");
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function buildInsightsIndexQuery(filters: InsightsIndexFilters): string {
  const params = new URLSearchParams();
  if (filters.domain.trim()) params.set("domain", filters.domain.trim());
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function buildNewsroomIndexWebPath(
  tab: NewsroomIndexTab,
  filters: ReferencesIndexFilters | MessagesIndexFilters | AssignmentsIndexFilters | InsightsIndexFilters,
): string {
  if (tab === "references") return `/newsroom/references${buildReferencesIndexQuery(filters as ReferencesIndexFilters)}`;
  if (tab === "messages") return `/newsroom/messages${buildMessagesIndexQuery(filters as MessagesIndexFilters)}`;
  if (tab === "insights") return `/newsroom/insights${buildInsightsIndexQuery(filters as InsightsIndexFilters)}`;
  return `/newsroom/assignments${buildAssignmentsIndexQuery(filters as AssignmentsIndexFilters)}`;
}

export function syncBrowserNewsroomIndexUrl(
  tab: NewsroomIndexTab,
  filters: ReferencesIndexFilters | MessagesIndexFilters | AssignmentsIndexFilters | InsightsIndexFilters,
  options?: { replace?: boolean },
) {
  if (typeof window === "undefined") return;
  const nextPath = buildNewsroomIndexWebPath(tab, filters);
  const current = `${window.location.pathname}${window.location.search}`;
  if (current === nextPath) return;
  if (options?.replace) window.history.replaceState(null, "", nextPath);
  else window.history.pushState(null, "", nextPath);
}

/** Lineage id from `/newsroom/references/<id>` (not index-only URLs). */
export function parseReferenceLineageIdFromNewsroomPathname(pathname: string | null | undefined): string | null {
  if (!pathname?.startsWith("/newsroom/references/")) return null;
  const segment = pathname.slice("/newsroom/references/".length).split("/")[0]?.trim() ?? "";
  if (!segment) return null;
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** Assignment id from `/newsroom/assignments/<id>` (not index-only URLs). */
export function parseAssignmentIdFromNewsroomPathname(pathname: string | null | undefined): string | null {
  if (!pathname?.startsWith("/newsroom/assignments/")) return null;
  const segment = pathname.slice("/newsroom/assignments/".length).split("/")[0]?.trim() ?? "";
  if (!segment) return null;
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

export function parseInsightThreadIdFromNewsroomPathname(pathname: string | null | undefined): string | null {
  if (!pathname?.startsWith("/newsroom/insights/")) return null;
  const segment = pathname.slice("/newsroom/insights/".length).split("/")[0]?.trim() ?? "";
  if (!segment) return null;
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
