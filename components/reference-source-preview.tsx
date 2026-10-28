"use client";

import { FullscreenIcon, XIcon } from "lucide-react";
import { useEffect, useId, useState } from "react";
import type { ReferenceAttachmentRecord } from "../lib/category-repository";
import {
  isPdfAttachment,
  resolveReferenceSourcePreview,
  type ReferenceSourcePreview,
} from "../lib/reference-source-preview";

function PdfSourcePreview({ preview }: { preview: Extract<ReferenceSourcePreview, { kind: "pdf" }> }) {
  const viewportTitleId = useId();
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [expanded]);

  return (
    <>
      <div
        className="news-desk-reference-source-preview news-desk-reference-source-preview--pdf"
        data-news-desk-reference-source-preview="pdf"
      >
        <div className="news-desk-reference-source-preview__pdf-card">
          <button
            aria-label="Expand PDF preview"
            className="news-desk-reference-source-preview__pdf-expand"
            onClick={() => setExpanded(true)}
            type="button"
          >
            <FullscreenIcon aria-hidden size={18} strokeWidth={2} />
          </button>
          <div className="news-desk-reference-source-preview__frame news-desk-reference-source-preview__frame--pdf">
            <iframe
              loading="lazy"
              referrerPolicy="strict-origin-when-cross-origin"
              src={preview.embedUrl}
              tabIndex={-1}
              title={preview.label}
            />
          </div>
        </div>
      </div>
      {expanded ? (
        <div
          aria-labelledby={viewportTitleId}
          aria-modal="true"
          className="news-desk-reference-source-preview__viewport"
          data-news-desk-reference-source-preview-viewport="open"
          role="dialog"
        >
          <header className="news-desk-reference-source-preview__viewport-strip">
            <span className="sr-only" id={viewportTitleId}>
              {preview.label}
            </span>
            <button
              aria-label="Close expanded PDF preview"
              className="news-desk-reference-source-preview__viewport-close"
              onClick={() => setExpanded(false)}
              type="button"
            >
              <XIcon aria-hidden size={18} strokeWidth={2} />
            </button>
          </header>
          <div className="news-desk-reference-source-preview__viewport-frame">
            <iframe
              referrerPolicy="strict-origin-when-cross-origin"
              src={preview.embedUrl}
              title={`${preview.label} (expanded)`}
            />
          </div>
        </div>
      ) : null}
    </>
  );
}

/** Session memory of the server's answers, so reopening an item does not ask again. */
const frameableAnswers = new Map<string, boolean>();

/** Whether the page allows being shown in a frame: null while asking. A refused frame would be an empty box, so it is not shown. */
function useFrameable(href: string | null): boolean | null {
  const [answer, setAnswer] = useState<boolean | null>(() => (href ? frameableAnswers.get(href) ?? null : null));
  useEffect(() => {
    if (!href) return undefined;
    const known = frameableAnswers.get(href);
    if (known !== undefined) { setAnswer(known); return undefined; }
    setAnswer(null);
    let active = true;
    fetch(`/api/newsroom/source-frameable?url=${encodeURIComponent(href)}`)
      .then((response) => (response.ok ? response.json() : { frameable: false }))
      .then((body: { frameable?: unknown }) => { frameableAnswers.set(href, body.frameable === true); if (active) setAnswer(body.frameable === true); })
      .catch(() => { if (active) setAnswer(false); });
    return () => { active = false; };
  }, [href]);
  return answer;
}

/**
 * The live preview of the source, or nothing at all: a YouTube video or a PDF always has one; a web page only when the page allows
 * being framed (asked of the server first). It sits under the link to the original, with no heading of its own.
 */
export function ReferenceSourcePreview({
  attachments = [],
  sourceUri,
}: {
  attachments?: ReferenceAttachmentRecord[];
  sourceUri?: string | null;
}) {
  const preview = resolveReferenceSourcePreview(sourceUri, attachments);
  const frameable = useFrameable(preview?.kind === "html" ? preview.href : null);
  const pendingPdfPreview = !preview && attachments.some(
    (attachment) => isPdfAttachment(attachment) && Boolean(attachment.storagePath),
  );
  if (!preview) {
    if (!pendingPdfPreview) return null;
    return (
      <p
        className="news-desk-reference-source-preview__hint news-desk-reference-source-preview__hint--pdf-loading"
        data-news-desk-reference-source-preview="pdf-loading"
      >
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
    return <PdfSourcePreview preview={preview} />;
  }

  if (frameable !== true) return null;
  return (
    <div
      className="news-desk-reference-source-preview news-desk-reference-source-preview--html"
      data-news-desk-reference-source-preview="html"
    >
      <div className="news-desk-reference-source-preview__frame">
        <iframe
          loading="lazy"
          referrerPolicy="strict-origin-when-cross-origin"
          sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
          src={preview.href}
          title={preview.label}
        />
      </div>
    </div>
  );
}
