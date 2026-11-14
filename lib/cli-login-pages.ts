import { NextResponse, type NextRequest } from "next/server";
import { readAmplifyOutputsFile } from "./amplify-outputs-path";

/**
 * `/cli/approve` and `/cli/callback`, the approval pages of `papyrus login --remote`.
 *
 * The pages themselves are the cli-login library's `ApprovalPages`, run by this site's pages function
 * (amplify/functions/cli-login-pages). This only forwards the browser's request to it with IAM and returns its answer,
 * Set-Cookie headers included. A site that has not switched remote CLI login on has no pages function in its Amplify
 * outputs, so these routes answer 404 and call nothing.
 */
export const CLI_PAGE_PATHS = ["/cli/approve", "/cli/callback"] as const;
export const CLI_PAGES_MAXIMUM_BODY_BYTES = 64 * 1024;

export interface ForwardedRequest {
  method: string;
  path: string;
  query: Record<string, string>;
  headers: Record<string, string>;
  body: string;
}

export interface ForwardedResponse {
  status: number;
  headers: [string, string][];
  body: string;
}

export type InvokePages = (functionArn: string, request: ForwardedRequest) => Promise<ForwardedResponse>;

export interface CliLoginPagesOptions {
  readOutputs?: () => { custom?: { cliLogin?: { pagesFunctionArn?: string } | null } } | null;
  invoke?: InvokePages;
}

const NO_STORE = { "cache-control": "no-store" };

function plain(status: number, text: string): NextResponse {
  return new NextResponse(text, { status, headers: { ...NO_STORE, "content-type": "text/plain; charset=utf-8" } });
}

export async function invokePagesFunction(functionArn: string, request: ForwardedRequest): Promise<ForwardedResponse> {
  const { InvokeCommand, LambdaClient } = await import("@aws-sdk/client-lambda");
  const region = /^arn:aws[a-z-]*:lambda:([a-z0-9-]+):/.exec(functionArn)?.[1];
  const response = await new LambdaClient(region ? { region } : {}).send(
    new InvokeCommand({ FunctionName: functionArn, InvocationType: "RequestResponse", Payload: Buffer.from(JSON.stringify(request)) }),
  );
  if (response.FunctionError || !response.Payload) throw new Error("cli-login pages function failed");
  return JSON.parse(Buffer.from(response.Payload).toString("utf8")) as ForwardedResponse;
}

function isForwardedResponse(value: unknown): value is ForwardedResponse {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<ForwardedResponse>;
  return (
    Number.isInteger(candidate.status) && (candidate.status as number) >= 200 && (candidate.status as number) <= 599
    && typeof candidate.body === "string"
    && Array.isArray(candidate.headers)
    && candidate.headers.every((pair) => Array.isArray(pair) && pair.length === 2 && typeof pair[0] === "string" && typeof pair[1] === "string")
  );
}

export async function handleCliLoginPage(request: NextRequest, options: CliLoginPagesOptions = {}): Promise<NextResponse> {
  const path = request.nextUrl.pathname;
  if (!(CLI_PAGE_PATHS as readonly string[]).includes(path)) return plain(404, "Not found.");
  const outputs = (options.readOutputs ?? (() => readAmplifyOutputsFile() as ReturnType<NonNullable<CliLoginPagesOptions["readOutputs"]>>))();
  const functionArn = outputs?.custom?.cliLogin?.pagesFunctionArn;
  if (!functionArn) {
    return NextResponse.json(
      { error: "cli_login_not_configured", message: "This site has not switched on remote CLI login." },
      { status: 404, headers: NO_STORE },
    );
  }
  const body = request.method === "POST" ? await request.text() : "";
  if (Buffer.byteLength(body, "utf8") > CLI_PAGES_MAXIMUM_BODY_BYTES) return plain(413, "Request too large.");
  const forwarded: ForwardedRequest = {
    method: request.method,
    path,
    query: Object.fromEntries(request.nextUrl.searchParams),
    headers: Object.fromEntries(request.headers),
    body,
  };
  let answer: unknown;
  try {
    answer = await (options.invoke ?? invokePagesFunction)(functionArn, forwarded);
  } catch {
    return plain(503, "Sign-in is unavailable. Try the approval link again in a moment.");
  }
  if (!isForwardedResponse(answer)) return plain(502, "Sign-in is unavailable. Try the approval link again in a moment.");
  const response = new NextResponse(answer.body, { status: answer.status });
  // Set-Cookie may repeat; every other header is set once, replacing the runtime's default (such as a text/plain content type).
  for (const [name, value] of answer.headers) {
    if (name.toLowerCase() === "set-cookie") response.headers.append(name, value);
    else response.headers.set(name, value);
  }
  return response;
}
