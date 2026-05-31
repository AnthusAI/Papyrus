"use client";

import type { ReferenceAttachmentRecord } from "../lib/category-repository";
import { isPdfAttachment, resolveReferenceSourcePreview } from "../lib/reference-source-preview";

export function ReferenceSourcePreview({
  attachments = [],
  sourceUri,
}: {
  attachments?: ReferenceAttachmentRecord[];
  sourceUri?: string | null;
}) {
  const preview = resolveReferenceSourcePreview(sourceUri, attachments);
  const pendingPdfPreview = !preview && attachments.some(
    (attachment) => isPdfAttachment(attachment) && Boolean(attachment.storagePath),
  );
  if (!preview) {
    if (!pendingPdfPreview) return null;
    return (
      <p className="news-desk-reference-source-preview__hint" data-news-desk-reference-source-preview="pdf-loading">
        Loading PDF preview…
      </p>
    );
  }

  if (preview.kind === "youtube") {
    return (
      <div
        className="news-desk-reference-source-preview news-desk-reference-source-preview--youtube"
        data-news-desk-reference-source-preview="youtube"
      >
        <div className="news-desk-reference-source-preview__frame">
          <iframe
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            allowFullScreen
            loading="lazy"
            referrerPolicy="strict-origin-when-cross-origin"
            src={preview.embedUrl}
            title={`YouTube preview ${preview.videoId}`}
          />
        </div>
        <p className="news-desk-reference-source-preview__actions">
          <a href={preview.watchUrl} rel="noopener noreferrer" target="_blank">
            Open on YouTube
          </a>
        </p>
      </div>
    );
  }

  if (preview.kind === "pdf") {
    return (
      <div
        className="news-desk-reference-source-preview news-desk-reference-source-preview--pdf"
        data-news-desk-reference-source-preview="pdf"
      >
        <div className="news-desk-reference-source-preview__frame news-desk-reference-source-preview__frame--pdf">
          <iframe
            loading="lazy"
            referrerPolicy="strict-origin-when-cross-origin"
            src={preview.embedUrl}
            title={preview.label}
          />
        </div>
        <p className="news-desk-reference-source-preview__actions">
          <a href={preview.href} rel="noopener noreferrer" target="_blank">
            {preview.label}
          </a>
        </p>
      </div>
    );
  }

  return (
    <div
      className="news-desk-reference-source-preview news-desk-reference-source-preview--html"
      data-news-desk-reference-source-preview="html"
    >
      <p className="news-desk-reference-source-preview__actions">
        <a href={preview.href} rel="noopener noreferrer" target="_blank">
          {preview.label}
        </a>
      </p>
    </div>
  );
}
