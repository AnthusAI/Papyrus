import { LAMBDA_DATA_AUTH_MODE, type LambdaDataClient } from "./lambda-data-client";

export const MESSAGE_KIND_EMAIL_SUBMISSION = "email_submission";
export const MESSAGE_DOMAIN_REFERENCE_INTAKE = "reference_intake";
export const MESSAGE_TYPE_INBOUND_EMAIL = "INBOUND_EMAIL";
export const RESPONSE_TARGET_EMAIL_PROCESSOR = "email_submission_processor";

const URL_PATTERN = /https?:\/\/[^\s<>"')\]]+/gi;
const DOI_PATTERN = /\b10\.\d{4,9}\/[-._;()/:A-Z0-9]+/gi;
const RESEARCH_ASSIGNMENT_PHRASES = [
  "research assignment",
  "assignment to research",
  "find sources on",
  "research the topic",
  "look into the topic",
  "investigate whether",
];

export function normalizeEmailAddress(value: string | null | undefined): string {
  const raw = String(value ?? "").trim().toLowerCase();
  if (!raw) return "";
  const match = raw.match(/<([^>]+)>/);
  return (match?.[1] ?? raw).trim().toLowerCase();
}

export function extractSenderFromSesMail(mail: Record<string, unknown>): string {
  const headers = mail.commonHeaders && typeof mail.commonHeaders === "object"
    ? (mail.commonHeaders as Record<string, unknown>)
    : {};
  const fromValues = Array.isArray(headers.from) ? headers.from : [];
  if (fromValues.length > 0) return normalizeEmailAddress(String(fromValues[0]));
  return normalizeEmailAddress(String(mail.source ?? ""));
}

export function extractSenderFromRawMime(rawBytes: Uint8Array): string {
  const raw = Buffer.from(rawBytes).toString("utf8");
  const fromMatch = raw.match(/^From:\s*(.*)$/im);
  return normalizeEmailAddress(fromMatch?.[1] ?? "");
}

export function extractRecipientsFromRawMime(rawBytes: Uint8Array): string[] {
  const raw = Buffer.from(rawBytes).toString("utf8");
  const recipients: string[] = [];
  for (const header of ["To", "Cc", "Delivered-To", "X-Original-To"]) {
    const regex = new RegExp(`^${header}:\\s*(.*)$`, "gim");
    let match: RegExpExecArray | null = regex.exec(raw);
    while (match) {
      for (const part of String(match[1]).split(",")) {
        const normalized = normalizeEmailAddress(part);
        if (normalized && !recipients.includes(normalized)) recipients.push(normalized);
      }
      match = regex.exec(raw);
    }
  }
  return recipients;
}

export function extractRecipientsFromSesMail(mail: Record<string, unknown>): string[] {
  const headers = mail.commonHeaders && typeof mail.commonHeaders === "object"
    ? (mail.commonHeaders as Record<string, unknown>)
    : {};
  const recipients: string[] = [];
  for (const key of ["to", "cc"] as const) {
    const values = headers[key];
    if (!Array.isArray(values)) continue;
    for (const entry of values) {
      const normalized = normalizeEmailAddress(String(entry));
      if (normalized) recipients.push(normalized);
    }
  }
  const destination = mail.destination;
  if (Array.isArray(destination)) {
    for (const entry of destination) {
      const normalized = normalizeEmailAddress(String(entry));
      if (normalized && !recipients.includes(normalized)) recipients.push(normalized);
    }
  }
  return recipients;
}

const SUBMISSION_MESSAGE_ID_PATTERN = /^(message-email-submission-[a-f0-9]{20})(?:@|$)/i;

export function parseInboundMimeThreading(rawBytes: Uint8Array): { inReplyTo: string | null; references: string | null } {
  const raw = Buffer.from(rawBytes).toString("utf8");
  const inReplyTo = raw.match(/^In-Reply-To:\s*(.+)$/im)?.[1]?.trim() ?? null;
  const references = raw.match(/^References:\s*(.+)$/im)?.[1]?.trim() ?? null;
  return { inReplyTo, references };
}

export function parseSubmissionMessageIdFromRfcMessageId(value: string | null | undefined): string | null {
  const raw = String(value ?? "").trim();
  if (!raw) return null;
  const tokens = raw.match(/<([^>]+)>/g)?.map((entry) => entry.slice(1, -1)) ?? [raw.replace(/^<|>$/g, "")];
  for (const token of tokens) {
    const match = SUBMISSION_MESSAGE_ID_PATTERN.exec(token.trim());
    if (match) return match[1];
    if (token.startsWith("message-email-submission-")) return token.split("@")[0];
  }
  return null;
}

export function resolveParentSubmissionMessageId(
  inReplyTo: string | null,
  references: string | null,
): string | null {
  for (const header of [inReplyTo, references]) {
    const resolved = parseSubmissionMessageIdFromRfcMessageId(header);
    if (resolved) return resolved;
  }
  return null;
}

export function countInboundAttachments(rawBytes: Uint8Array): number {
  const raw = Buffer.from(rawBytes).toString("utf8");
  let count = 0;
  const parts = raw.split(/\r?\n\r?\n/);
  for (let index = 0; index < parts.length; index += 1) {
    const headerBlock = parts[index];
    if (!headerBlock || !/Content-Type:/i.test(headerBlock)) continue;
    const disposition = headerBlock.match(/Content-Disposition:\s*([^\r\n;]+)/i)?.[1]?.trim().toLowerCase() ?? "";
    const contentType = headerBlock.match(/Content-Type:\s*([^;\r\n]+)/i)?.[1]?.trim().toLowerCase() ?? "";
    const filename = headerBlock.match(/(?:name|filename)=["']?([^"';\r\n]+)/i)?.[1]?.trim() ?? "";
    const isPdf = contentType === "application/pdf" || filename.toLowerCase().endsWith(".pdf");
    if (disposition === "attachment" || (disposition !== "inline" && isPdf && filename)) {
      count += 1;
    }
  }
  if (count > 0) return count;
  const legacyMatches = raw.match(/Content-Disposition:\s*attachment/gi);
  return legacyMatches?.length ?? 0;
}

const MIN_COMPOSED_PROSE_CHARS_FOR_AGENT = 120;

export function proseAfterStrippingCitations(
  bodyText: string,
  citations: Array<{ url?: string }>,
): string {
  let text = String(bodyText ?? "");
  for (const citation of citations) {
    const url = String(citation.url ?? "").trim();
    if (url) text = text.split(url).join(" ");
  }
  text = text.replace(/https?:\/\/\S+/gi, " ");
  return text.replace(/\s+/g, " ").trim();
}

export function hasSubstantialComposedProse(
  bodyText: string,
  citations: Array<{ url?: string }>,
): boolean {
  const prose = proseAfterStrippingCitations(bodyText, citations);
  if (prose.length >= MIN_COMPOSED_PROSE_CHARS_FOR_AGENT) return true;
  const clauses = prose.split(/[.!?\n]+/).map((entry) => entry.trim()).filter((entry) => entry.length >= 24);
  return clauses.length >= 2;
}

export function classifyNewSubmissionIntake(
  bodyText: string,
  citations: Array<Record<string, unknown>>,
  attachmentCount = 0,
): string {
  const hasPdfAttachments = attachmentCount > 0;
  if (citations.length > 0 && hasPdfAttachments) return "agent_intake";
  if (citations.length === 0 && hasPdfAttachments) {
    if (attachmentCount > 1) return "agent_intake";
    if (hasSubstantialComposedProse(bodyText, [])) return "agent_intake";
    return "pdf_only_intake";
  }
  if (citations.length === 0) return "new_submission";
  if (citations.length > 1) return "agent_intake";
  if (hasSubstantialComposedProse(bodyText, citations as Array<{ url?: string }>)) return "agent_intake";
  return "direct_citation_intake";
}

export function classifyInboundEmailIntake(input: {
  bodyText: string;
  citations: Array<Record<string, unknown>>;
  parentSubmissionMessageId: string | null;
  attachmentCount: number;
  userComposedText: string;
}): string {
  if (input.parentSubmissionMessageId) {
    if (input.attachmentCount > 0 && !input.userComposedText) return "attachment_only_reply";
    if (input.userComposedText || input.attachmentCount > 0) return "conversational_reply";
    return "empty_reply";
  }
  return classifyNewSubmissionIntake(input.bodyText, input.citations, input.attachmentCount);
}

export function extractUserComposedReplyText(bodyText: string): string {
  let text = String(bodyText ?? "").replace(/\r\n/g, "\n");
  const markers = [
    /\nOn .+ wrote:\s*\n/i,
    /\n-{2,}\s*Original Message\s*-{2,}\s*\n/i,
    /\nFrom:\s*.+\n/i,
  ];
  let earliest: number | null = null;
  for (const marker of markers) {
    const match = marker.exec(text);
    if (match && (earliest === null || match.index < earliest)) earliest = match.index;
  }
  if (earliest !== null && earliest > 0) text = text.slice(0, earliest);
  const lines: string[] = [];
  for (const line of text.split("\n")) {
    if (line.startsWith(">")) break;
    lines.push(line);
  }
  return lines.join("\n").trim();
}

export function parseInboundEmailBody(rawBytes: Uint8Array): { subject: string; text: string } {
  const raw = Buffer.from(rawBytes).toString("utf8");
  const subjectMatch = raw.match(/^Subject:\s*(.*)$/im);
  const subject = subjectMatch?.[1]?.trim() ?? "";
  const plainMatch = raw.match(/Content-Type:\s*text\/plain[\s\S]*?\r?\n\r?\n([\s\S]*?)(?:\r?\n--|$)/i);
  let text = plainMatch?.[1]?.trim() ?? "";
  const htmlMatch = !plainMatch
    ? raw.match(/Content-Type:\s*text\/html[\s\S]*?\r?\n\r?\n([\s\S]*?)(?:\r?\n--|$)/i)
    : null;
  if (!plainMatch && htmlMatch) {
    text = htmlToText(htmlMatch[1] ?? "");
  }
  // For multipart MIME, do not fall back to the raw object (PDF parts may contain DOI-like tokens).
  if (!plainMatch && !htmlMatch && !/Content-Type:\s*multipart\//i.test(raw)) {
    const bodyIndex = raw.indexOf("\r\n\r\n");
    text = bodyIndex >= 0 ? raw.slice(bodyIndex + 4).trim() : raw.trim();
  }
  return { subject, text };
}

function htmlToText(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function extractDirectCitations(text: string): Array<{ kind: string; url: string; title: string; ingestion_rationale: string; doi?: string }> {
  const citations: Array<{ kind: string; url: string; title: string; ingestion_rationale: string; doi?: string }> = [];
  const seen = new Set<string>();
  for (const match of text.matchAll(URL_PATTERN)) {
    const url = match[0].replace(/[.,);]+$/, "");
    if (seen.has(url)) continue;
    seen.add(url);
    citations.push({
      kind: "url",
      url,
      title: titleFromUrl(url),
      ingestion_rationale: directCitationRationale(url),
    });
  }
  for (const match of text.matchAll(DOI_PATTERN)) {
    const doi = match[0].replace(/[.,);]+$/, "");
    const url = `https://doi.org/${doi}`;
    if (seen.has(url)) continue;
    seen.add(url);
    citations.push({
      kind: "doi",
      url,
      doi,
      title: `DOI ${doi}`,
      ingestion_rationale: directCitationRationale(url),
    });
  }
  return citations;
}

export function looksLikeResearchAssignmentRequest(text: string, citationCount: number): boolean {
  if (citationCount > 0) return false;
  const lowered = text.toLowerCase();
  return RESEARCH_ASSIGNMENT_PHRASES.some((phrase) => lowered.includes(phrase));
}

export async function lookupRegisteredUserProfileId(client: LambdaDataClient, senderEmail: string): Promise<string | null> {
  const normalized = normalizeEmailAddress(senderEmail);
  if (!normalized) return null;

  const identityModel = client.models.UserIdentity as {
    listUserIdentitiesByEmailAndStatus?: (
      input: { email: string; status?: { eq?: string } },
      options?: { limit?: number; authMode?: typeof LAMBDA_DATA_AUTH_MODE },
    ) => Promise<{ data?: Array<{ userProfileId?: string | null; status?: string | null }> | null; errors?: unknown }>;
  };
  if (typeof identityModel.listUserIdentitiesByEmailAndStatus === "function") {
    const response = await identityModel.listUserIdentitiesByEmailAndStatus(
      { email: normalized, status: { eq: "active" } },
      { limit: 10, authMode: LAMBDA_DATA_AUTH_MODE },
    );
    for (const identity of response.data ?? []) {
      if (!identity) continue;
      const profileId = String(identity.userProfileId ?? "").trim();
      if (profileId) return profileId;
    }
  }

  const profiles = await listAllRecords(client.models.UserProfile);
  for (const profile of profiles) {
    if (normalizeEmailAddress(String(profile.email ?? "")) === normalized) {
      return String(profile.id ?? "").trim() || null;
    }
  }
  return null;
}

async function listAllRecords(model: { list?: (options?: { limit?: number; nextToken?: string | null | undefined; authMode?: typeof LAMBDA_DATA_AUTH_MODE }) => Promise<{ data?: Array<Record<string, unknown>> | null; nextToken?: string | null }> }): Promise<Array<Record<string, unknown>>> {
  const items: Array<Record<string, unknown>> = [];
  let nextToken: string | null | undefined;
  do {
    const response = await model.list?.({
      limit: 200,
      nextToken: nextToken ?? undefined,
      authMode: LAMBDA_DATA_AUTH_MODE,
    });
    items.push(...(response?.data ?? []));
    nextToken = response?.nextToken;
  } while (nextToken);
  return items;
}

export function buildEmailSubmissionMessageInput(input: {
  id: string;
  now: string;
  subject: string;
  bodyText: string;
  senderEmail: string;
  recipientEmail: string;
  sesMessageId: string | null;
  s3Bucket: string | null;
  s3Key: string | null;
  authorized: boolean;
  authorUserProfileId: string | null;
  authorLabel: string;
  citations: Array<Record<string, unknown>>;
  status: string;
  responseStatus: string;
  responseError: string | null;
  parentSubmissionMessageId?: string | null;
  intakeClassification?: string | null;
  inboundInReplyTo?: string | null;
  inboundReferences?: string | null;
  inboundAttachmentCount?: number;
}) {
  const record: Record<string, unknown> = {
    id: input.id,
    messageKind: MESSAGE_KIND_EMAIL_SUBMISSION,
    messageDomain: MESSAGE_DOMAIN_REFERENCE_INTAKE,
    messageType: MESSAGE_TYPE_INBOUND_EMAIL,
    status: input.status,
    summary: input.subject || "Email submission",
    source: "inbound-email",
    authorLabel: input.authorLabel,
    role: "submitter",
    content: input.bodyText,
    semanticLayer: "private",
    searchVisibility: "private",
    responseTarget: RESPONSE_TARGET_EMAIL_PROCESSOR,
    responseStatus: input.responseStatus,
    responseOwner: "papyrus-ses-inbound-receive",
    responseStartedAt: input.responseStatus === "IN_PROGRESS" ? input.now : null,
    responseCompletedAt: ["COMPLETED", "FAILED", "REJECTED"].includes(input.responseStatus) ? input.now : null,
    responseError: input.responseError,
    metadata: JSON.stringify({
      channel: "email",
      senderEmail: input.senderEmail,
      recipientEmail: input.recipientEmail,
      sesMessageId: input.sesMessageId,
      s3Bucket: input.s3Bucket,
      s3Key: input.s3Key,
      authorized: input.authorized,
      directCitationCount: input.citations.length,
      directCitations: input.citations,
      parentSubmissionMessageId: input.parentSubmissionMessageId ?? null,
      intakeClassification: input.intakeClassification ?? null,
      inboundInReplyTo: input.inboundInReplyTo ?? null,
      inboundReferences: input.inboundReferences ?? null,
      inboundAttachmentCount: input.inboundAttachmentCount ?? 0,
    }),
    createdAt: input.now,
    updatedAt: input.now,
    newsroomFeedKey: "submissions",
  };
  if (input.authorUserProfileId) {
    record.authorUserProfileId = input.authorUserProfileId;
  }
  return record;
}

function titleFromUrl(url: string): string {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.replace(/^www\./, "");
    const segment = parsed.pathname.split("/").filter(Boolean).pop() ?? "";
    const cleaned = segment.replace(/[-_]+/g, " ").trim();
    return cleaned ? cleaned.slice(0, 120) : host;
  } catch {
    return url;
  }
}

function directCitationRationale(source: string): string {
  return `Direct citation submitted by email: ${source}. This is explicit source material for reference create/find/process intake, not a research assignment.`;
}
