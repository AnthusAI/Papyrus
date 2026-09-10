"use client";

import {
  ArchiveIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ExternalLinkIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import {
  parseReferenceLineageIdFromNewsroomPathname,
  syncBrowserNewsroomIndexUrl,
} from "../lib/newsroom-index-filters";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import {
  countReferencesByStatus,
  filterReferencesByStatus,
  formatReferenceListDate,
  referenceDisplayTitle,
  referenceLineageId,
  referenceStatusBadgeVariant,
  referenceStatusLabel,
  selectedReferenceRecordByLineage,
  selectCanonicalReferenceRecords,
  type ReferenceCurationAction,
  type ReferenceStatusFilter,
} from "../lib/newsroom-references";
import { normalizeReferenceCurationStatus } from "../lib/reference-policy";
import { newsroomListRowClassName } from "../lib/newsroom-list-selection";
import { ReferenceSourcePreview } from "./reference-source-preview";
import {
  loadReferenceAttachmentsForLineageId,
  loadStoragePathUrl,
} from "./news-desk-taxonomy-client";

type NewsroomReferencesViewProps = {
  demo?: boolean;
  disabled?: boolean;
  initialReferenceLineageId?: string | null;
  onReview: (reference: ReferenceRecord, action: ReferenceCurationAction) => void;
  referenceAttachments?: ReferenceAttachmentRecord[];
  references: ReferenceRecord[];
};

const STATUS_FILTERS: Array<{ key: ReferenceStatusFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "accepted", label: "Accepted" },
  { key: "rejected", label: "Rejected" },
  { key: "archived", label: "Archived" },
];

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mediaQuery = window.matchMedia(query);
    const update = () => setMatches(mediaQuery.matches);
    update();
    mediaQuery.addEventListener("change", update);
    return () => mediaQuery.removeEventListener("change", update);
  }, [query]);
  return matches;
}

function buildReferenceDetailPath(lineageId: string, demo?: boolean): string {
  return getNewsroomNavHref(`/newsroom/references/${encodeURIComponent(lineageId)}`, demo);
}

function referenceUrl(reference: ReferenceRecord): string | null {
  const candidate = reference.sourceUri?.trim() || reference.storagePath?.trim() || null;
  if (!candidate) return null;
  if (/^https?:\/\//i.test(candidate)) return candidate;
  return null;
}

function normalizeReferenceDetailHttpUri(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return null;
}

function useReferencePreviewAttachments(
  reference: ReferenceRecord | null,
  referenceAttachments: ReferenceAttachmentRecord[],
) {
  const lineageId = reference ? referenceLineageId(reference) : "";
  const seededAttachments = useMemo(
    () => referenceAttachments.filter((attachment) => attachment.referenceLineageId === lineageId),
    [lineageId, referenceAttachments],
  );
  const [attachments, setAttachments] = useState<ReferenceAttachmentRecord[]>(seededAttachments);
  const [attachmentLinksById, setAttachmentLinksById] = useState<Record<string, string>>({});

  useEffect(() => {
    setAttachments(seededAttachments);
  }, [seededAttachments]);

  useEffect(() => {
    if (!lineageId) return;
    if (seededAttachments.length > 0) return;
    let active = true;
    void loadReferenceAttachmentsForLineageId(lineageId)
      .then((loaded) => {
        if (!active || !loaded.length) return;
        setAttachments(loaded);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [lineageId, seededAttachments.length]);

  useEffect(() => {
    if (!attachments.length) {
      setAttachmentLinksById({});
      return;
    }
    let active = true;
    const staticLinks = new Map<string, string>();
    const storageLookups: Array<{ id: string; storagePath: string }> = [];

    for (const attachment of attachments) {
      if (attachment.storagePath) {
        storageLookups.push({ id: attachment.id, storagePath: attachment.storagePath });
        continue;
      }
      const sourceHref = normalizeReferenceDetailHttpUri(attachment.sourceUri);
      if (sourceHref) staticLinks.set(attachment.id, sourceHref);
    }

    if (!storageLookups.length) {
      setAttachmentLinksById(Object.fromEntries(staticLinks.entries()));
      return () => {
        active = false;
      };
    }

    setAttachmentLinksById(Object.fromEntries(staticLinks.entries()));
    void Promise.all(storageLookups.map(async (lookup) => {
      const result = await loadStoragePathUrl(lookup.storagePath);
      return { id: lookup.id, url: result.url };
    }))
      .then((resolved) => {
        if (!active) return;
        const nextLinks = Object.fromEntries(staticLinks.entries());
        for (const entry of resolved) {
          if (entry.url) nextLinks[entry.id] = entry.url;
        }
        setAttachmentLinksById(nextLinks);
      })
      .catch(() => undefined);

    return () => {
      active = false;
    };
  }, [attachments]);

  const previewAttachments = useMemo(
    () => attachments.map((attachment) => ({
      ...attachment,
      sourceUri: attachmentLinksById[attachment.id] ?? attachment.sourceUri,
    })),
    [attachmentLinksById, attachments],
  );

  return previewAttachments;
}

function ReferenceDetailPanel({
  demo,
  disabled,
  onReview,
  previewAttachments,
  reference,
  onClose,
}: {
  demo?: boolean;
  disabled?: boolean;
  onReview: (action: ReferenceCurationAction) => void;
  previewAttachments: ReferenceAttachmentRecord[];
  reference: ReferenceRecord;
  onClose?: () => void;
}) {
  const lineageId = referenceLineageId(reference);
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  const url = referenceUrl(reference);
  const acceptDisabled = disabled || status === "accepted";
  const rejectDisabled = disabled || status === "rejected";
  const archiveDisabled = disabled || status === "archived";

  return (
    <div
      className="flex h-full flex-col font-sans"
      data-news-desk-reference-detail={lineageId}
    >
      <div className="space-y-4 p-4">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={referenceStatusBadgeVariant(status)}>{referenceStatusLabel(status)}</Badge>
            {reference.corpusId ? (
              <Badge variant="outline">{reference.corpusId}</Badge>
            ) : null}
          </div>
          <h2 className="text-lg font-semibold leading-snug text-foreground">{referenceDisplayTitle(reference)}</h2>
          {reference.externalItemId ? (
            <p className="text-sm text-muted-foreground">{reference.externalItemId}</p>
          ) : null}
        </div>

        <div
          className="flex flex-wrap items-center gap-2"
          data-news-desk-reference-curation-cluster
          data-reference-curation-status={status}
        >
          <Button
            aria-label="Accept reference"
            aria-pressed={status === "accepted"}
            data-news-desk-reference-accept
            disabled={acceptDisabled}
            onClick={() => onReview("accept")}
            size="sm"
            type="button"
            variant={status === "accepted" ? "default" : "outline"}
          >
            <ThumbsUpIcon className="size-4" />
            Accept
          </Button>
          <Button
            aria-label="Reject reference"
            aria-pressed={status === "rejected"}
            data-news-desk-reference-reject
            disabled={rejectDisabled}
            onClick={() => onReview("reject")}
            size="sm"
            type="button"
            variant={status === "rejected" ? "destructive" : "outline"}
          >
            <ThumbsDownIcon className="size-4" />
            Reject
          </Button>
          <Button
            aria-label="Archive reference"
            disabled={archiveDisabled}
            onClick={() => onReview("archive")}
            size="sm"
            type="button"
            variant="outline"
          >
            <ArchiveIcon className="size-4" />
            Archive
          </Button>
        </div>

        <Separator />

        <section aria-label="Source preview" className="space-y-2">
          <h3 className="text-sm font-medium text-foreground">Source preview</h3>
          <ReferenceSourcePreview attachments={previewAttachments} sourceUri={reference.sourceUri} />
        </section>

        <dl className="grid gap-3 text-sm">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Why</dt>
            <dd className="mt-1 text-foreground">
              {reference.curationStatusReason?.trim()
                || "Private corpus item awaiting editorial review for evidence use."}
            </dd>
          </div>
          {url ? (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Source</dt>
              <dd className="mt-1">
                <a
                  className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
                  href={url}
                  rel="noreferrer"
                  target="_blank"
                >
                  {url}
                  <ExternalLinkIcon className="size-3.5" aria-hidden="true" />
                </a>
              </dd>
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Imported</dt>
              <dd className="mt-1 text-foreground">{formatReferenceListDate(reference)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Media</dt>
              <dd className="mt-1 text-foreground">{reference.mediaType ?? "unknown"}</dd>
            </div>
          </div>
        </dl>

        <section aria-label="Attachments">
          <h3 className="mb-2 text-sm font-medium text-foreground">Attachments</h3>
          {previewAttachments.length ? (
            <ul className="space-y-1 text-sm text-muted-foreground">
              {previewAttachments.map((attachment) => (
                <li key={attachment.id}>
                  {attachment.sourceUri ? (
                    <a className="text-primary underline-offset-4 hover:underline" href={attachment.sourceUri} rel="noreferrer" target="_blank">
                      {attachment.filename ?? attachment.role ?? attachment.id}
                    </a>
                  ) : (
                    <span>{attachment.filename ?? attachment.role ?? attachment.id}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              {reference.storagePath
                ? reference.storagePath
                : "No attachment metadata on this record."}
            </p>
          )}
        </section>

        {onClose ? (
          <Button className="w-full" onClick={onClose} type="button" variant="secondary">
            Close
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function NewsroomReferencesView({
  demo = false,
  disabled = false,
  initialReferenceLineageId = null,
  onReview,
  referenceAttachments = [],
  references,
}: NewsroomReferencesViewProps) {
  const pathname = usePathname();
  const isMobileDetail = useMediaQuery("(max-width: 767px)");
  const pathnameLineageId = useMemo(
    () => parseReferenceLineageIdFromNewsroomPathname(pathname),
    [pathname],
  );
  const routeLineageId = initialReferenceLineageId ?? pathnameLineageId ?? "";

  const canonicalReferences = useMemo(() => selectCanonicalReferenceRecords(references), [references]);
  const statusCounts = useMemo(() => countReferencesByStatus(canonicalReferences), [canonicalReferences]);

  const [statusFilter, setStatusFilter] = useState<ReferenceStatusFilter>("all");
  const [selectedLineageId, setSelectedLineageId] = useState(routeLineageId);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(Boolean(routeLineageId) && isMobileDetail);

  const filteredReferences = useMemo(
    () => filterReferencesByStatus(canonicalReferences, statusFilter),
    [canonicalReferences, statusFilter],
  );

  const selectedReference = useMemo(
    () => selectedReferenceRecordByLineage(filteredReferences, selectedLineageId)
      ?? selectedReferenceRecordByLineage(canonicalReferences, selectedLineageId),
    [canonicalReferences, filteredReferences, selectedLineageId],
  );

  const previewAttachments = useReferencePreviewAttachments(selectedReference, referenceAttachments);

  const selectedIndex = selectedReference
    ? filteredReferences.findIndex((entry) => referenceLineageId(entry) === referenceLineageId(selectedReference))
    : -1;
  const previousReference = selectedIndex > 0 ? filteredReferences[selectedIndex - 1] : null;
  const nextReference = selectedIndex >= 0 && selectedIndex < filteredReferences.length - 1
    ? filteredReferences[selectedIndex + 1]
    : null;

  const syncStatusUrl = useCallback((nextStatus: ReferenceStatusFilter) => {
    if (demo) return;
    syncBrowserNewsroomIndexUrl("references", {
      status: nextStatus === "all" ? "" : nextStatus,
      processing: "",
      order: "published",
    }, { replace: true });
  }, [demo]);

  useEffect(() => {
    if (!routeLineageId) return;
    setSelectedLineageId(routeLineageId);
    if (isMobileDetail) setMobileDetailOpen(true);
  }, [isMobileDetail, routeLineageId]);

  useEffect(() => {
    if (isMobileDetail) return;
    setMobileDetailOpen(false);
  }, [isMobileDetail]);

  const selectReference = (lineageId: string) => {
    setSelectedLineageId(lineageId);
    if (isMobileDetail) setMobileDetailOpen(true);
    if (typeof window !== "undefined") {
      const nextPath = buildReferenceDetailPath(lineageId, demo);
      if (`${window.location.pathname}${window.location.search}` !== nextPath) {
        window.history.pushState(null, "", nextPath);
      }
    }
  };

  const closeDetail = () => {
    setMobileDetailOpen(false);
    setSelectedLineageId("");
    if (typeof window !== "undefined") {
      const indexPath = getNewsroomNavHref("/newsroom/references", demo);
      window.history.replaceState(null, "", indexPath);
    }
  };

  const runReview = (action: ReferenceCurationAction) => {
    if (!selectedReference) return;
    onReview(selectedReference, action);
  };

  const emptyLabel = canonicalReferences.length
    ? "No references match this filter."
    : "No private references imported yet.";

  return (
    <div
      className="flex min-h-0 flex-1 flex-col gap-4 md:max-h-[calc(100dvh-8.5rem)] md:flex-row"
      data-news-desk-section="references"
      data-detail-open={selectedReference || routeLineageId ? "true" : "false"}
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 md:overflow-hidden">
        <div className="shrink-0 space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">References</h2>
          <p className="text-sm text-muted-foreground">
            Review source intake before it becomes accepted evidence.
          </p>
        </div>

        <Tabs
          className="shrink-0"
          defaultValue="all"
          onValueChange={(value) => {
            const next = value as ReferenceStatusFilter;
            setStatusFilter(next);
            syncStatusUrl(next);
          }}
          value={statusFilter}
        >
          <TabsList className="h-auto w-full flex-wrap justify-start gap-1 bg-muted/40 p-1">
            {STATUS_FILTERS.map((filter) => {
              const count = filter.key === "all"
                ? canonicalReferences.length
                : statusCounts[filter.key] ?? 0;
              return (
                <TabsTrigger className="text-xs sm:text-sm" key={filter.key} value={filter.key}>
                  {filter.label}
                  <Badge className="ml-1.5 min-w-5 px-1.5" variant="secondary">{count}</Badge>
                </TabsTrigger>
              );
            })}
          </TabsList>
        </Tabs>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-2 pb-4" data-newsroom-card-grid>
            {filteredReferences.length ? filteredReferences.map((reference) => {
              const lineageId = referenceLineageId(reference);
              const status = normalizeReferenceCurationStatus(reference.curationStatus);
              const active = selectedLineageId === lineageId;
              return (
                <button
                  aria-current={active ? "true" : undefined}
                  className={newsroomListRowClassName(active)}
                  data-newsroom-list-row
                  data-selected={active || undefined}
                  data-newsroom-card
                  data-newsroom-card-id={lineageId}
                  key={lineageId}
                  onClick={() => selectReference(lineageId)}
                  type="button"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="truncate text-sm font-medium text-foreground">{referenceDisplayTitle(reference)}</p>
                      <p className="truncate text-xs text-muted-foreground">{reference.corpusId}</p>
                    </div>
                    <Badge variant={referenceStatusBadgeVariant(status)}>{referenceStatusLabel(status)}</Badge>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{formatReferenceListDate(reference)}</p>
                </button>
              );
            }) : (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">No references</CardTitle>
                  <CardDescription>{emptyLabel}</CardDescription>
                </CardHeader>
              </Card>
            )}
          </div>
        </ScrollArea>
      </div>

      <div
        className="hidden min-h-0 w-full shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-card md:flex md:w-[min(100%,24rem)] lg:w-[min(100%,28rem)]"
        data-newsroom-list-detail-shell
        data-news-desk-section="references"
        data-detail-open={selectedReference ? "true" : "false"}
      >
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-2">
          <span className="text-sm font-medium text-foreground">Detail</span>
          <div className="newsroom-list-detail-shell__detail-toolbar-trailing flex items-center gap-1">
            <Button
              aria-label="Previous"
              disabled={!previousReference}
              onClick={() => previousReference && selectReference(referenceLineageId(previousReference))}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <ChevronLeftIcon className="size-4" />
            </Button>
            <Button
              aria-label="Next"
              disabled={!nextReference}
              onClick={() => nextReference && selectReference(referenceLineageId(nextReference))}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <ChevronRightIcon className="size-4" />
            </Button>
          </div>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          {selectedReference ? (
            <ReferenceDetailPanel
              demo={demo}
              disabled={disabled}
              onReview={runReview}
              previewAttachments={previewAttachments}
              reference={selectedReference}
            />
          ) : (
            <CardContent className="p-4 text-sm text-muted-foreground">
              Select a reference to inspect curation details.
            </CardContent>
          )}
        </ScrollArea>
      </div>

      {isMobileDetail ? (
        <Sheet
          onOpenChange={(open) => {
            if (!open) closeDetail();
            else setMobileDetailOpen(true);
          }}
          open={mobileDetailOpen && Boolean(selectedReference)}
        >
          <SheetContent className="gap-0 p-0" side="bottom">
            <SheetHeader className="border-b border-border px-4 py-3">
              <SheetTitle className="text-left text-base">Reference</SheetTitle>
            </SheetHeader>
            {selectedReference ? (
              <ScrollArea className="max-h-[75dvh]">
                <ReferenceDetailPanel
                  demo={demo}
                  disabled={disabled}
                  onClose={closeDetail}
                  onReview={runReview}
                  previewAttachments={previewAttachments}
                  reference={selectedReference}
                />
              </ScrollArea>
            ) : null}
          </SheetContent>
        </Sheet>
      ) : null}
    </div>
  );
}
