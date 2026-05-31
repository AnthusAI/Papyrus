import type { ReferenceAttachmentRecord } from "./category-repository";

export type ReferenceSourcePreview =
  | {
      kind: "youtube";
      videoId: string;
      embedUrl: string;
      thumbnailUrl: string;
      watchUrl: string;
    }
  | {
      kind: "pdf";
      href: string;
      label: string;
      embedUrl: string;
    }
  | {
      kind: "html";
      href: string;
      label: string;
    };

export function youtubeVideoIdFromUri(sourceUri: string): string | null {
  try {
    const parsed = new URL(sourceUri);
    const host = parsed.hostname.toLowerCase();
    if (host === "youtu.be") {
      const token = parsed.pathname.replace(/^\/+/, "").split("/")[0] ?? "";
      return token || null;
    }
    if (host === "youtube.com" || host === "www.youtube.com" || host === "m.youtube.com") {
      const fromQuery = parsed.searchParams.get("v");
      if (fromQuery) return fromQuery;
      if (parsed.pathname.startsWith("/shorts/")) {
        return parsed.pathname.slice("/shorts/".length).split("/")[0] || null;
      }
    }
  } catch {
    return null;
  }
  return null;
}

export function isPdfAttachment(attachment: ReferenceAttachmentRecord): boolean {
  const mediaType = (attachment.mediaType ?? "").toLowerCase();
  if (mediaType.includes("pdf")) return true;
  const path = `${attachment.storagePath ?? ""} ${attachment.sourceUri ?? ""} ${attachment.filename ?? ""}`.toLowerCase();
  return path.includes(".pdf");
}

function isHtmlAttachment(attachment: ReferenceAttachmentRecord): boolean {
  const mediaType = (attachment.mediaType ?? "").toLowerCase();
  if (mediaType.includes("html")) return true;
  const path = `${attachment.storagePath ?? ""} ${attachment.sourceUri ?? ""} ${attachment.filename ?? ""}`.toLowerCase();
  return path.endsWith(".html") || path.endsWith(".htm");
}

export function isCitationLandingPageUrl(uri: string): boolean {
  try {
    const parsed = new URL(uri);
    const host = parsed.hostname.toLowerCase();
    const path = parsed.pathname.toLowerCase();
    if (host.endsWith("arxiv.org") && path.startsWith("/abs/")) return true;
    if (host === "doi.org" || host.endsWith(".doi.org")) return true;
    if (host.includes("pubmed") && path.includes("/")) return true;
    return false;
  } catch {
    return false;
  }
}

export function isDirectPdfUrl(uri: string): boolean {
  try {
    const parsed = new URL(uri);
    if (parsed.pathname.toLowerCase().endsWith(".pdf")) return true;
    if (parsed.searchParams.get("response-content-type")?.toLowerCase().includes("pdf")) return true;
  } catch {
    return uri.toLowerCase().includes(".pdf");
  }
  return uri.toLowerCase().includes(".pdf");
}

export function pickPdfAttachmentHref(
  attachment: ReferenceAttachmentRecord,
  referenceSourceUri?: string | null,
): string | null {
  const candidates = [attachment.sourceUri, referenceSourceUri].filter(
    (value): value is string => Boolean(value?.trim()),
  );

  for (const candidate of candidates) {
    if (isDirectPdfUrl(candidate)) return candidate;
  }

  for (const candidate of candidates) {
    if (!isCitationLandingPageUrl(candidate)) return candidate;
  }

  return null;
}

function pdfPreviewFromUri(sourceUri: string | null | undefined): ReferenceSourcePreview | null {
  if (!sourceUri) return null;
  if (!isDirectPdfUrl(sourceUri)) return null;
  return {
    kind: "pdf",
    href: sourceUri,
    embedUrl: sourceUri,
    label: "Open PDF source",
  };
}

function htmlPreviewFromUri(sourceUri: string | null | undefined): ReferenceSourcePreview | null {
  if (!sourceUri) return null;
  try {
    const parsed = new URL(sourceUri);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    if (youtubeVideoIdFromUri(sourceUri)) return null;
    const lowerPath = parsed.pathname.toLowerCase();
    if (lowerPath.endsWith(".pdf")) return null;
    return { kind: "html", href: sourceUri, label: "Open web source" };
  } catch {
    return null;
  }
}

export function resolveReferenceSourcePreview(
  sourceUri: string | null | undefined,
  attachments: ReferenceAttachmentRecord[] = [],
): ReferenceSourcePreview | null {
  const videoId = sourceUri ? youtubeVideoIdFromUri(sourceUri) : null;
  if (videoId) {
    const watchUrl = `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`;
    return {
      kind: "youtube",
      videoId,
      embedUrl: `https://www.youtube-nocookie.com/embed/${encodeURIComponent(videoId)}`,
      thumbnailUrl: `https://i.ytimg.com/vi/${encodeURIComponent(videoId)}/hqdefault.jpg`,
      watchUrl,
    };
  }

  const pdfAttachment = attachments.find((attachment) => isPdfAttachment(attachment));
  if (pdfAttachment) {
    const href = pickPdfAttachmentHref(pdfAttachment, sourceUri);
    if (href) {
      return {
        kind: "pdf",
        href,
        embedUrl: href,
        label: pdfAttachment.filename ?? "Open PDF attachment",
      };
    }
  }

  const pdfFromUri = pdfPreviewFromUri(sourceUri);
  if (pdfFromUri) return pdfFromUri;

  const htmlAttachment = attachments.find((attachment) => isHtmlAttachment(attachment));
  if (htmlAttachment) {
    const candidates = [htmlAttachment.sourceUri, htmlAttachment.storagePath, sourceUri].filter(
      (value): value is string => Boolean(value?.trim()),
    );
    const href = candidates.find((candidate) => !isCitationLandingPageUrl(candidate)) ?? candidates[0];
    if (href) {
      return {
        kind: "html",
        href,
        label: htmlAttachment.filename ?? "Open HTML attachment",
      };
    }
  }

  return htmlPreviewFromUri(sourceUri);
}
