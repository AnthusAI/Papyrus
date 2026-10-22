import { NextResponse, type NextRequest } from "next/server";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";
import { loadProspectusSessionSealingSecret, type ProspectusSignedInSession } from "./prospectus-session";
import { signedInProspectusSession } from "./prospectus-sign-in-routes";
import { readerIsStaff, readerSubject } from "./reader-subject";
import { SiteOriginNotConfiguredError, publicSiteOrigin, siteOriginNotConfiguredResponse } from "./site-origin";

export const READER_ACTIONS_FUNCTION_ENV = "PAPYRUS_READER_ACTIONS_FUNCTION";
export const READER_MAXIMUM_BODY_BYTES = 4096;
export const READER_MAXIMUM_SUBJECTS = 50;
export const READER_SUBJECT_KEY = /^[A-Za-z0-9._:-]{1,200}$/;

export type ReaderAction = "me" | "handle" | "vote" | "rating";

export interface ReaderActionEvent {
  publication: string;
  siteSubject: string;
  isStaff: boolean;
  action: ReaderAction;
  payload: Record<string, unknown>;
}

export interface ReaderActionResult {
  statusCode: number;
  body: Record<string, unknown>;
}

export type ReaderActionInvoker = (functionName: string, event: ReaderActionEvent) => Promise<ReaderActionResult>;

export interface ReaderApiOptions {
  environment?: Record<string, string | undefined>;
  invoke?: ReaderActionInvoker;
  actionsFunctionName?: string | null;
  loadSealingSecret?: () => Promise<string | null>;
  nowInSeconds?: number;
}

const NO_STORE_HEADERS = { "cache-control": "no-store" };

function failure(status: number, error: string, message: string, extra: Record<string, unknown> = {}, headers: Record<string, string> = {}): NextResponse {
  return NextResponse.json({ error, message, ...extra }, { status, headers: { ...NO_STORE_HEADERS, ...headers } });
}

export function identityUnavailableResponse(): NextResponse {
  return failure(503, "reader_identity_unavailable", "Reader sign-in is not open yet.");
}

function actionsFunctionNameFrom(options: ReaderApiOptions, environment: Record<string, string | undefined>): string | null {
  if (options.actionsFunctionName !== undefined) return options.actionsFunctionName;
  const fromEnvironment = (environment[READER_ACTIONS_FUNCTION_ENV] ?? "").trim();
  if (fromEnvironment) return fromEnvironment;
  const outputs = readAmplifyOutputsFile() as { custom?: { readerSteering?: { actionsFunction?: unknown } | null } } | null;
  const fromOutputs = outputs?.custom?.readerSteering?.actionsFunction;
  return typeof fromOutputs === "string" && fromOutputs.trim() ? fromOutputs.trim() : null;
}

export async function invokeReaderActionsLambda(functionName: string, event: ReaderActionEvent): Promise<ReaderActionResult> {
  const { InvokeCommand, LambdaClient } = await import("@aws-sdk/client-lambda");
  const response = await new LambdaClient({}).send(
    new InvokeCommand({ FunctionName: functionName, InvocationType: "RequestResponse", Payload: Buffer.from(JSON.stringify(event)) }),
  );
  if (response.FunctionError || !response.Payload) throw new Error("reader-actions failed");
  const result = JSON.parse(Buffer.from(response.Payload).toString("utf8")) as Partial<ReaderActionResult>;
  if (typeof result.statusCode !== "number" || typeof result.body !== "object" || result.body === null) throw new Error("reader-actions returned an unexpected shape");
  return { statusCode: result.statusCode, body: result.body as Record<string, unknown> };
}

async function readJsonBody(request: NextRequest): Promise<{ payload: Record<string, unknown> } | { response: NextResponse }> {
  const contentType = (request.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (contentType !== "application/json") return { response: failure(415, "unsupported_media_type", "Send application/json.") };
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > READER_MAXIMUM_BODY_BYTES) return { response: failure(413, "payload_too_large", "The request body is too large.") };
  const text = await request.text();
  if (Buffer.byteLength(text, "utf8") > READER_MAXIMUM_BODY_BYTES) return { response: failure(413, "payload_too_large", "The request body is too large.") };
  try {
    const parsed = JSON.parse(text) as unknown;
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("not an object");
    return { payload: parsed as Record<string, unknown> };
  } catch {
    return { response: failure(400, "invalid_json", "The request body is not a JSON object.") };
  }
}

function subjectsFromQuery(request: NextRequest): { payload: Record<string, unknown> } | { response: NextResponse } {
  const raw = request.nextUrl.searchParams.get("subjects") ?? "";
  const subjects = raw === "" ? [] : raw.split(",");
  if (subjects.length > READER_MAXIMUM_SUBJECTS || !subjects.every((subject) => READER_SUBJECT_KEY.test(subject))) {
    return { response: failure(400, "invalid_subjects", `Send at most ${READER_MAXIMUM_SUBJECTS} comma separated item keys.`) };
  }
  return { payload: { subjects } };
}

async function signedInReaderSession(request: NextRequest, options: ReaderApiOptions): Promise<ProspectusSignedInSession | null | "unavailable"> {
  const sealingSecret = await (options.loadSealingSecret ?? (() => loadProspectusSessionSealingSecret({ environment: options.environment })))();
  if (!sealingSecret) return "unavailable";
  return signedInProspectusSession(request, sealingSecret, options.nowInSeconds);
}

/**
 * One reader route: session, readerSubject (503 while Prospectus has no siteSubject), Origin, JSON size, then the
 * reader-actions function. The siteSubject only travels to the function and never into a response.
 */
export async function handleReaderRequest(request: NextRequest, action: ReaderAction, options: ReaderApiOptions = {}): Promise<NextResponse> {
  const environment = options.environment ?? process.env;
  let origin: string;
  try {
    origin = publicSiteOrigin(request, environment);
  } catch (error) {
    if (error instanceof SiteOriginNotConfiguredError) return siteOriginNotConfiguredResponse(error);
    throw error;
  }
  const session = await signedInReaderSession(request, options);
  if (session === "unavailable") return identityUnavailableResponse();
  if (!session) return failure(401, "signed_out", "Sign in to continue.");
  const siteSubject = readerSubject(session, environment);
  if (siteSubject === null) return identityUnavailableResponse();

  let parsed: { payload: Record<string, unknown> } | { response: NextResponse };
  if (action === "me") {
    parsed = subjectsFromQuery(request);
  } else {
    if (request.headers.get("origin") !== origin) return failure(403, "origin_mismatch", "This request did not come from this site.");
    parsed = await readJsonBody(request);
  }
  if ("response" in parsed) return parsed.response;

  const functionName = actionsFunctionNameFrom(options, environment);
  if (!functionName) return failure(503, "reader_actions_unavailable", "Reader features are not enabled for this site.");
  try {
    const result = await (options.invoke ?? invokeReaderActionsLambda)(functionName, {
      publication: new URL(origin).host,
      siteSubject,
      isStaff: readerIsStaff(session),
      action,
      payload: parsed.payload,
    });
    const retryAfter: Record<string, string> = typeof result.body.retryAfter === "number" ? { "retry-after": String(result.body.retryAfter) } : {};
    return NextResponse.json(result.body, { status: result.statusCode, headers: { ...NO_STORE_HEADERS, ...retryAfter } });
  } catch (error) {
    console.error(`Reader action ${action} failed (${error instanceof Error ? error.name : "error"}).`);
    return failure(502, "reader_actions_failed", "Reader features could not be reached.");
  }
}
