import { readAmplifyOutputsFile } from "../amplify-outputs-path";

export type McpPrincipal = { kind: "staff"; subject: string; accessToken: string; idToken: string; expiresAt?: number }
  | { kind: "reader"; siteSubject: string };
export type McpOAuthRequest =
  | { operation: "verify"; token: string; resource: string }
  | { operation: "exchange"; code: string; client: string; redirect: string; resource: string; verifier: string }
  | { operation: "refresh"; token: string; client: string; resource: string }
  | { operation: "revoke"; token: string; client: string }
  | { operation: "issue"; client: string; redirect: string; resource: string; challenge: string; principal: McpPrincipal; upstream_expiry: number; transaction_id: string };
export type McpOAuthResult = { principal: McpPrincipal | null } | { code: string }
  | { access_token: string; refresh_token: string; token_type: "Bearer"; expires_in: number }
  | { error: "invalid_grant" | "invalid_request" } | Record<string, never>;
export type McpOAuthConfig = { functionArn: string; origin: string };

type Options = { readOutputs?: () => { custom?: { mcpOAuth?: McpOAuthConfig } } | null;
  invoke?: (arn: string, request: McpOAuthRequest) => Promise<unknown> };

export function mcpOAuthConfig(options: Options = {}): McpOAuthConfig | null {
  const outputs = (options.readOutputs ?? (() => readAmplifyOutputsFile() as ReturnType<NonNullable<Options["readOutputs"]>>))();
  const config = outputs?.custom?.mcpOAuth;
  if (!config || !/^arn:aws[a-z-]*:lambda:[a-z0-9-]+:\d{12}:function:.+$/.test(config.functionArn)) return null;
  try { const url = new URL(config.origin); if (url.protocol !== "https:" || url.origin !== config.origin) return null; }
  catch { return null; }
  return config;
}

async function invokeLambda(arn: string, request: McpOAuthRequest): Promise<unknown> {
  const { InvokeCommand, LambdaClient } = await import("@aws-sdk/client-lambda");
  const region = arn.split(":")[3];
  const response = await new LambdaClient({ region }).send(new InvokeCommand({ FunctionName: arn, InvocationType: "RequestResponse", Payload: Buffer.from(JSON.stringify(request)) }));
  if (response.FunctionError || !response.Payload) throw new Error("MCP OAuth service failed");
  return JSON.parse(Buffer.from(response.Payload).toString("utf8"));
}

function isResult(operation: McpOAuthRequest["operation"], result: unknown): result is McpOAuthResult {
  if (!result || typeof result !== "object" || Array.isArray(result)) return false;
  const value = result as Record<string, unknown>;
  if (value.error === "invalid_grant" || value.error === "invalid_request") return true;
  if (operation === "revoke") return Object.keys(value).length === 0;
  if (operation === "issue") return typeof value.code === "string" && value.code.length > 0;
  if (operation === "verify") {
    if (value.principal === null) return true;
    if (!value.principal || typeof value.principal !== "object") return false;
    const principal = value.principal as Record<string, unknown>;
    return principal.kind === "staff" ? typeof principal.subject === "string" && !!principal.subject && typeof principal.accessToken === "string" && !!principal.accessToken && typeof principal.idToken === "string" && !!principal.idToken
      : principal.kind === "reader" && typeof principal.siteSubject === "string" && /^ss1_[A-Za-z0-9_-]{43}$/.test(principal.siteSubject);
  }
  return typeof value.access_token === "string" && !!value.access_token && typeof value.refresh_token === "string" && !!value.refresh_token
    && value.token_type === "Bearer" && typeof value.expires_in === "number" && Number.isSafeInteger(value.expires_in) && value.expires_in > 0;
}

/** A null principal is an invalid token; exceptions mean unavailable and must be mapped to 503. */
export async function invokeMcpOAuth(request: McpOAuthRequest, options: Options = {}): Promise<McpOAuthResult> {
  const config = mcpOAuthConfig(options);
  if (!config) throw new Error("MCP OAuth is not configured");
  const result = await (options.invoke ?? invokeLambda)(config.functionArn, request);
  if (!isResult(request.operation, result)) throw new Error("MCP OAuth returned an invalid response");
  return result;
}
