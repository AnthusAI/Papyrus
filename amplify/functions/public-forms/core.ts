import { createHash, randomUUID } from "node:crypto";

/**
 * The public form receiving endpoint, without any AWS in it: `handlePublicFormRequest` takes the Function URL
 * event plus a store and a rate limiter, so every rule here is exercised by `scripts/test-public-forms.ts`.
 *
 * Contract (docs/public-forms.md): POST JSON from one of the site's own origins; the answer never reflects input.
 */

export const FORM_SUBMISSION_MESSAGE_KIND = "form_submission";
export const FORM_SUBMISSION_MESSAGE_DOMAIN = "inbox";
export const FORM_SUBMISSION_FEED_KEY = "messages";
export const NEWSLETTER_FORM_ID = "newsletter";
export const NEWSLETTER_MESSAGE_TYPE = "newsletter_signup";
export const DEFAULT_FORM_ID = "contact";
export const DEFAULT_HONEYPOT_FIELDS = ["website"];

export type PublicFormsConfig = {
  /** Exact origins (scheme + host [+ port]) the browser may post from. Empty: every request is refused. */
  allowedOrigins: string[];
  /** Field names that, when filled, mark a bot. */
  honeypotFields: string[];
  maxBodyBytes: number;
  maxFields: number;
  maxValueLength: number;
  /** Submissions one address may make per `ipWindowSeconds`, across all forms. */
  ipLimit: number;
  ipWindowSeconds: number;
  /** Submissions one form accepts per hour from everyone; and the whole site across all form ids. */
  formLimitPerHour: number;
  siteLimitPerHour: number;
};

export const DEFAULT_PUBLIC_FORMS_CONFIG: PublicFormsConfig = {
  allowedOrigins: [],
  honeypotFields: DEFAULT_HONEYPOT_FIELDS,
  maxBodyBytes: 16 * 1024,
  maxFields: 20,
  maxValueLength: 5000,
  ipLimit: 10,
  ipWindowSeconds: 600,
  formLimitPerHour: 120,
  siteLimitPerHour: 400,
};

export type FormSubmissionRecord = {
  id: string;
  messageKind: typeof FORM_SUBMISSION_MESSAGE_KIND;
  messageDomain: string;
  messageType: string;
  status: "active";
  summary: string;
  content: string;
  source: string;
  authorLabel: string;
  searchVisibility: "private";
  responseTarget: "none";
  responseStatus: "COMPLETED";
  metadata: string;
  createdAt: string;
  updatedAt: string;
  newsroomFeedKey: string;
};

export type SubmissionStore = { save(record: FormSubmissionRecord): Promise<void> };

/** `hit` counts one event in the window and answers whether it is still within `limit`. */
export type RateLimiter = {
  hit(scope: string, subject: string, windowSeconds: number, limit: number): Promise<boolean>;
};

export type PublicFormsDeps = {
  store: SubmissionStore;
  limiter: RateLimiter;
  now?: () => Date;
  newId?: () => string;
};

export type FunctionUrlEvent = {
  rawQueryString?: string;
  headers?: Record<string, string | undefined>;
  body?: string | null;
  isBase64Encoded?: boolean;
  requestContext?: { http?: { method?: string; sourceIp?: string } };
};

export type FunctionUrlResult = { statusCode: number; headers: Record<string, string>; body: string };

const FORM_ID = /^[a-z0-9][a-z0-9-]{0,39}$/;
const FIELD_NAME = /^[A-Za-z][A-Za-z0-9_]{0,39}$/;
const EMAIL = /^[^\s@<>"]+@[^\s@<>"]+\.[^\s@<>"]+$/;
const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g;

export function parseOrigins(value: string | undefined): string[] {
  const origins: string[] = [];
  for (const entry of (value ?? "").split(",")) {
    const trimmed = entry.trim();
    if (trimmed === "") continue;
    try {
      const url = new URL(trimmed);
      if (url.protocol === "https:" || url.hostname === "localhost") origins.push(url.origin);
    } catch {
      // An unparsable origin is dropped: the allow-list can only get stricter.
    }
  }
  return [...new Set(origins)];
}

function positiveInteger(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function configFromEnvironment(env: Record<string, string | undefined>): PublicFormsConfig {
  const honeypots = (env.PAPYRUS_PUBLIC_FORMS_HONEYPOTS ?? "").split(",").map((entry) => entry.trim()).filter(Boolean);
  return {
    ...DEFAULT_PUBLIC_FORMS_CONFIG,
    allowedOrigins: parseOrigins(env.PAPYRUS_PUBLIC_FORMS_ORIGINS),
    honeypotFields: [...new Set([...DEFAULT_HONEYPOT_FIELDS, ...honeypots])],
    ipLimit: positiveInteger(env.PAPYRUS_PUBLIC_FORMS_IP_LIMIT, DEFAULT_PUBLIC_FORMS_CONFIG.ipLimit),
    formLimitPerHour: positiveInteger(env.PAPYRUS_PUBLIC_FORMS_FORM_LIMIT, DEFAULT_PUBLIC_FORMS_CONFIG.formLimitPerHour),
    siteLimitPerHour: positiveInteger(env.PAPYRUS_PUBLIC_FORMS_SITE_LIMIT, DEFAULT_PUBLIC_FORMS_CONFIG.siteLimitPerHour),
  };
}

function reply(statusCode: number, body: Record<string, unknown> | null, headers: Record<string, string> = {}): FunctionUrlResult {
  return {
    statusCode,
    headers: { "Cache-Control": "no-store", "Content-Type": "application/json", "X-Content-Type-Options": "nosniff", ...headers },
    body: body === null ? "" : JSON.stringify(body),
  };
}

function header(event: FunctionUrlEvent, name: string): string {
  const headers = event.headers ?? {};
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === name && typeof value === "string") return value;
  }
  return "";
}

function clean(value: string, multiline: boolean): string {
  const stripped = value.replace(CONTROL, "").replace(/\r\n?/g, "\n");
  return (multiline ? stripped : stripped.replace(/\n/g, " ")).trim();
}

type Parsed =
  | { ok: true; formId: string; fields: Record<string, string>; page: string; honeypotFilled: boolean }
  | { ok: false; error: string };

function parseSubmission(event: FunctionUrlEvent, config: PublicFormsConfig): Parsed {
  const raw = event.isBase64Encoded === true ? Buffer.from(event.body ?? "", "base64").toString("utf8") : (event.body ?? "");
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return { ok: false, error: "invalid-json" };
  }
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return { ok: false, error: "invalid-body" };
  const entries = Object.entries(payload as Record<string, unknown>);
  if (entries.length > config.maxFields) return { ok: false, error: "too-many-fields" };

  const fields: Record<string, string> = {};
  let formId = "";
  let page = "";
  let honeypotFilled = false;
  for (const [name, value] of entries) {
    if (!FIELD_NAME.test(name)) return { ok: false, error: "invalid-field" };
    if (value === null || value === undefined) continue;
    if (typeof value !== "string") return { ok: false, error: "invalid-field" };
    if (value.length > config.maxValueLength) return { ok: false, error: "field-too-long" };
    if (config.honeypotFields.includes(name)) {
      if (value.trim() !== "") honeypotFilled = true;
      continue;
    }
    if (name === "form") formId = value.trim().toLowerCase();
    else if (name === "page") page = clean(value, false).slice(0, 500);
    else fields[name] = clean(value, name === "message");
  }
  return { ok: true, formId, fields, page, honeypotFilled };
}

function queryFormId(event: FunctionUrlEvent): string {
  const match = /(?:^|&)form=([^&]*)/.exec(event.rawQueryString ?? "");
  if (match === null) return "";
  try {
    return decodeURIComponent(match[1]).trim().toLowerCase();
  } catch {
    return "";
  }
}

function ipSubject(ip: string): string {
  return createHash("sha256").update(`papyrus-public-forms:${ip}`).digest("hex").slice(0, 32);
}

export function buildSubmissionRecord(input: {
  id: string;
  formId: string;
  fields: Record<string, string>;
  page: string;
  origin: string;
  receivedAt: string;
}): FormSubmissionRecord {
  const { formId, fields } = input;
  const newsletter = formId === NEWSLETTER_FORM_ID;
  const name = fields.name ?? "";
  const email = fields.email ?? "";
  const topic = fields.topic ?? "";
  const message = fields.message ?? "";
  const who = name !== "" ? (email !== "" ? `${name} <${email}>` : name) : email;
  const headline = newsletter ? "Newsletter signup" : topic !== "" ? `${formId}: ${topic}` : formId;
  const lines = [`Form: ${formId}`];
  for (const [key, value] of Object.entries(fields)) {
    if (key === "message" || value === "") continue;
    lines.push(`${key}: ${value}`);
  }
  if (input.page !== "") lines.push(`page: ${input.page}`);
  const content = message !== "" ? `${lines.join("\n")}\n\n${message}` : lines.join("\n");
  const summarySource = message !== "" ? message.replace(/\s+/g, " ") : "";
  const summary = `${headline}${who !== "" ? ` from ${who}` : ""}${summarySource !== "" ? `: ${summarySource}` : ""}`.slice(0, 200);
  return {
    id: input.id,
    messageKind: FORM_SUBMISSION_MESSAGE_KIND,
    messageDomain: FORM_SUBMISSION_MESSAGE_DOMAIN,
    messageType: newsletter ? NEWSLETTER_MESSAGE_TYPE : FORM_SUBMISSION_MESSAGE_KIND,
    status: "active",
    summary,
    content,
    source: "public-form",
    authorLabel: who !== "" ? who.slice(0, 200) : "Anonymous visitor",
    searchVisibility: "private",
    responseTarget: "none",
    responseStatus: "COMPLETED",
    metadata: JSON.stringify({
      kind: newsletter ? NEWSLETTER_MESSAGE_TYPE : FORM_SUBMISSION_MESSAGE_KIND,
      formId,
      topic,
      fields,
      page: input.page,
      origin: input.origin,
      receivedAt: input.receivedAt,
    }),
    createdAt: input.receivedAt,
    updatedAt: input.receivedAt,
    newsroomFeedKey: FORM_SUBMISSION_FEED_KEY,
  };
}

export async function handlePublicFormRequest(
  event: FunctionUrlEvent,
  config: PublicFormsConfig,
  deps: PublicFormsDeps,
): Promise<FunctionUrlResult> {
  const method = (event.requestContext?.http?.method ?? "").toUpperCase();
  const origin = header(event, "origin");
  const allowed = origin !== "" && config.allowedOrigins.includes(origin);
  const cors: Record<string, string> = allowed
    ? {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "600",
        Vary: "Origin",
      }
    : { Vary: "Origin" };

  if (method === "OPTIONS") return allowed ? reply(204, null, cors) : reply(403, { ok: false, error: "origin-not-allowed" }, cors);
  if (method !== "POST") return reply(405, { ok: false, error: "method-not-allowed" }, { ...cors, Allow: "POST, OPTIONS" });
  if (!allowed) return reply(403, { ok: false, error: "origin-not-allowed" }, cors);
  if (!/^application\/json\s*(;|$)/i.test(header(event, "content-type"))) return reply(415, { ok: false, error: "unsupported-media-type" }, cors);

  const bodyBytes = Buffer.byteLength(event.body ?? "", event.isBase64Encoded === true ? "base64" : "utf8");
  if (bodyBytes > config.maxBodyBytes) return reply(413, { ok: false, error: "payload-too-large" }, cors);

  const parsed = parseSubmission(event, config);
  if (!parsed.ok) return reply(400, { ok: false, error: parsed.error }, cors);
  // A filled honeypot looks like success to the bot and stores nothing.
  if (parsed.honeypotFilled) return reply(200, { ok: true }, cors);

  const formId = parsed.formId || queryFormId(event) || DEFAULT_FORM_ID;
  if (!FORM_ID.test(formId)) return reply(400, { ok: false, error: "invalid-form" }, cors);
  const { fields } = parsed;
  const email = fields.email ?? "";
  if (email !== "" && (email.length > 254 || !EMAIL.test(email))) return reply(400, { ok: false, error: "invalid-email" }, cors);
  if (formId === NEWSLETTER_FORM_ID && email === "") return reply(400, { ok: false, error: "email-required" }, cors);
  if (email === "" && (fields.message ?? "") === "") return reply(400, { ok: false, error: "empty-submission" }, cors);

  const subject = ipSubject(event.requestContext?.http?.sourceIp ?? "unknown");
  let within: boolean;
  try {
    within =
      (await deps.limiter.hit("ip", subject, config.ipWindowSeconds, config.ipLimit))
      && (await deps.limiter.hit("form", formId, 3600, config.formLimitPerHour))
      && (await deps.limiter.hit("site", "all", 3600, config.siteLimitPerHour));
  } catch {
    return reply(503, { ok: false, error: "unavailable" }, cors);
  }
  if (!within) return reply(429, { ok: false, error: "rate-limited" }, { ...cors, "Retry-After": "600" });

  const receivedAt = (deps.now ?? (() => new Date()))().toISOString();
  const id = (deps.newId ?? (() => `form-${randomUUID().replace(/-/g, "")}`))();
  try {
    await deps.store.save(buildSubmissionRecord({ id, formId, fields, page: parsed.page, origin, receivedAt }));
  } catch {
    // Never pretend a submission was received when it was not.
    return reply(500, { ok: false, error: "store-failed" }, cors);
  }
  return reply(200, { ok: true }, cors);
}
