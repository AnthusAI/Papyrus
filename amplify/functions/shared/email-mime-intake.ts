import {
  directCitationRationale,
  collectMimeBodies,
  extractDirectCitations,
  titleFromUrl,
} from "./email-submission";

const HREF_PATTERN = /href\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))/gi;
const SKIP_URL_MARKERS = [
  "unsubscribe",
  "list-unsubscribe",
  "/unsubscribe",
  "mailchi.mp/unsubscribe",
  "/opt-out",
  "preferences",
  "email-preferences",
  "doubleclick.net",
  "facebook.com/sharer",
  "twitter.com/intent",
  "linkedin.com/sharing",
  "fonts.googleapis.com",
];
const SKIP_URL_PREFIXES = ["mailto:", "tel:", "javascript:", "cid:", "#"];

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/g, "'");
}

export function normalizeHrefUrl(raw: string): string | null {
  let url = decodeHtmlEntities(String(raw ?? "").trim());
  if (!url) return null;
  if (url.startsWith("//")) url = `https:${url}`;
  if (url.startsWith("<") && url.endsWith(">")) url = url.slice(1, -1).trim();
  const lowered = url.toLowerCase();
  if (SKIP_URL_PREFIXES.some((prefix) => lowered.startsWith(prefix))) return null;
  if (!/^https?:\/\//i.test(url)) return null;
  return url.replace(/[.,);]+$/, "");
}

export function isSkippableNewsletterUrl(url: string): boolean {
  const lowered = String(url ?? "").toLowerCase();
  if (SKIP_URL_MARKERS.some((marker) => lowered.includes(marker))) return true;
  if (/\.(png|jpe?g|gif|webp)(\?|$)/i.test(lowered)) return true;
  return false;
}

export function extractHrefUrlsFromHtml(html: string): string[] {
  const urls: string[] = [];
  const seen = new Set<string>();
  for (const match of html.matchAll(HREF_PATTERN)) {
    const candidate = normalizeHrefUrl(match[1] ?? match[2] ?? match[3] ?? "");
    if (!candidate || seen.has(candidate) || isSkippableNewsletterUrl(candidate)) continue;
    seen.add(candidate);
    urls.push(candidate);
  }
  return urls;
}

export function extractDirectCitationsFromIntake(input: {
  bodyText: string;
  htmlParts?: string[];
}): Array<{ kind: string; url: string; title: string; ingestion_rationale: string; doi?: string }> {
  const citations = extractDirectCitations(input.bodyText);
  const seen = new Set(citations.map((entry) => entry.url));
  for (const htmlPart of input.htmlParts ?? []) {
    for (const url of extractHrefUrlsFromHtml(htmlPart)) {
      if (seen.has(url)) continue;
      seen.add(url);
      citations.push({
        kind: "url",
        url,
        title: titleFromUrl(url),
        ingestion_rationale: directCitationRationale(url),
      });
    }
  }
  return citations;
}

function htmlToText(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function parseInboundMimeForIntake(rawBytes: Uint8Array): {
  subject: string;
  bodyText: string;
  htmlParts: string[];
  citations: Array<{ kind: string; url: string; title: string; ingestion_rationale: string; doi?: string }>;
} {
  const { subject, plain, html } = collectMimeBodies(rawBytes);
  const bodyText = plain.length > 0 ? plain.join("\n\n").trim() : htmlToText(html.join("\n\n"));
  return {
    subject: subject || "(no subject)",
    bodyText,
    htmlParts: html,
    citations: extractDirectCitationsFromIntake({ bodyText, htmlParts: html }),
  };
}
