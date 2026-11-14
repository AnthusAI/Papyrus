"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import { referenceLineageId } from "../lib/newsroom-references";
import { loadReferenceAttachmentsForLineageId, loadStoragePathUrl } from "./news-desk-taxonomy-client";

function normalizeReferenceDetailHttpUri(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return null;
}

/** The attachments of one Reference (seeded, else read), with stored files turned into links. Shared by the References detail pane and the Needs me detail pane. */
export function useReferencePreviewAttachments(
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
