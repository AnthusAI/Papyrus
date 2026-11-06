import { randomBytes, timingSafeEqual } from "node:crypto";
import { safeMcpRedirect } from "./oauth-clients";
import { openProspectusCookie, sealProspectusCookie } from "../prospectus-session";

type Principal = { kind: "staff"; subject: string; accessToken: string; idToken: string; expiresAt?: number } | { kind: "reader"; siteSubject: string };
type Operation = { operation: "issue"; client: string; redirect: string; resource: string; challenge: string; principal: Principal; upstream_expiry: number; transaction_id: string } | { operation: "exchange"; code: string; client: string; redirect: string; resource: string; verifier: string } | { operation: "refresh"; token: string; client: string; resource: string } | { operation: "revoke"; token: string; client: string };
type Options = { readerSignInAvailable?: boolean; readerSignIn?: (request: Request) => Promise<Response>; origin: string; clients: Record<string, string[]>; secret: string; invoke: (request: Operation) => Promise<Record<string, unknown>>; identity: (request: Request, kind: "staff" | "reader") => Promise<{ principal: Principal; upstream_expiry: number } | null> };
type Transaction = { client: string; redirect: string; resource: string; challenge: string; state: string; csrf: string };
const cookieName = "__Host-papyrus-mcp-consent";
const noStore = { "Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff" };
const json = (value: object, status = 200) => Response.json(value, { status, headers: noStore });
const failure = (status: number, error: string) => json({ error }, status);
const escapeHtml = (value: string) => value.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const form = async (request: Request) => {
  if (!/^application\/x-www-form-urlencoded(?:\s*;|\s*$)/i.test(request.headers.get("content-type") ?? "")) return null;
  const reader = request.body?.getReader();
  if (!reader) return null;
  const chunks: Uint8Array[] = []; let length = 0;
  try {
    while (true) { const next = await reader.read(); if (next.done) break; length += next.value.byteLength; if (length > 16384) { await reader.cancel(); return null; } chunks.push(next.value); }
  } catch { return null; }
  const bytes = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let text: string;
  try { text = new TextDecoder("utf-8", { fatal: true }).decode(bytes); } catch { return null; }
  const params = new URLSearchParams(text);
  if ([...params.keys()].some(key => params.getAll(key).length !== 1)) return null;
  return params;
};
const readCookie = (request: Request) => request.headers.get("cookie")?.split(";").map(x => x.trim()).find(x => x.startsWith(`${cookieName}=`))?.slice(cookieName.length + 1);


export function oauthMetadata(origin: string, name: "resource" | "metadata") {
  const resource = `${origin}/api/mcp`;
  return name === "resource"
    ? json({ resource, authorization_servers: [origin], bearer_methods_supported: ["header"] })
    : json({ issuer: origin, authorization_endpoint: `${origin}/api/mcp/oauth/authorize`, token_endpoint: `${origin}/api/mcp/oauth/token`, revocation_endpoint: `${origin}/api/mcp/oauth/revoke`, response_types_supported: ["code"], grant_types_supported: ["authorization_code", "refresh_token"], token_endpoint_auth_methods_supported: ["none"], code_challenge_methods_supported: ["S256"], authorization_response_iss_parameter_supported: true });
}

export function createOAuthHttp(options: Options) {
  const { origin, clients, secret, invoke, identity } = options;
  const resource = `${origin}/api/mcp`;
  const registered = (client: string, redirect: string) => Object.hasOwn(clients, client) && safeMcpRedirect(redirect) && clients[client].includes(redirect);
  return {
    resource: async () => oauthMetadata(origin, "resource"),
    metadata: async () => oauthMetadata(origin, "metadata"),
    authorize: async (request: Request) => {
      const params = new URL(request.url).searchParams;
      if ([...params.keys()].some(key => params.getAll(key).length !== 1)) return failure(400, "invalid_request");
      const client = params.get("client_id") ?? "", redirect = params.get("redirect_uri") ?? "", challenge = params.get("code_challenge") ?? "", state = params.get("state") ?? "";
      if (!registered(client, redirect) || params.get("resource") !== resource || params.get("response_type") !== "code" || params.get("code_challenge_method") !== "S256" || !/^[A-Za-z0-9_-]{43}$/.test(challenge) || state.length > 1024) return failure(400, "invalid_request");
      const tx: Transaction = { client, redirect, resource, challenge, state, csrf: randomBytes(32).toString("base64url") };
      const expires = Math.floor(Date.now() / 1000) + 300;
      const sealed = sealProspectusCookie(secret, cookieName, tx, expires);
      return new Response(null, { status: 303, headers: { ...noStore, Location: `${origin}/mcp/authorize`, "Set-Cookie": `${cookieName}=${sealed}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=300` } });
    },
    consent: async (request: Request) => {
      const tx = openProspectusCookie<Transaction>(secret, cookieName, readCookie(request));
      if (!tx || !registered(tx.client, tx.redirect) || tx.resource !== resource) return new Response("<!doctype html><html><head><title>Authorization expired</title></head><body><main><h1>Authorization expired</h1><p>Return to your client and start authorization again.</p></main></body></html>", { status: 400, headers: { ...noStore, "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'" } });
      if (request.method === "GET") {
        if (new URL(request.url).searchParams.get("sign_in") === "reader") {
          if (options.readerSignInAvailable === false || !options.readerSignIn) return failure(404, "invalid_request");
          return options.readerSignIn(request);
        }
        const html = `<!doctype html><html><head><meta charset="utf-8"><title>Authorize client</title></head><body><main><h1>Authorize client</h1><p>Allow ${escapeHtml(tx.client)} to access this publication as you?</p><p>Return address: ${escapeHtml(tx.redirect)}</p><form method="post"><input type="hidden" name="csrf" value="${escapeHtml(tx.csrf)}"><label><input type="radio" name="identity" value="staff" required> Staff</label><label><input type="radio" name="identity" value="reader" required> Reader</label><button name="decision" value="allow">Allow</button><button name="decision" value="deny">Deny</button></form></main></body></html>`;
        return new Response(html, { headers: { ...noStore, "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": `default-src 'none'; form-action 'self' ${new URL(tx.redirect).origin}; frame-ancestors 'none'; base-uri 'none'`, "Referrer-Policy": "same-origin" } });
      }
      if (request.method !== "POST") return failure(405, "invalid_request");
      if (request.headers.get("origin") !== origin) return failure(403, "invalid_request");
      const params = await form(request), csrf = params?.get("csrf") ?? "";
      const a = Buffer.from(csrf), b = Buffer.from(tx.csrf);
      if (a.length !== b.length || !timingSafeEqual(a, b) || !["allow", "deny"].includes(params?.get("decision") ?? "")) return failure(403, "invalid_request");
      const target = new URL(tx.redirect);
      target.searchParams.delete("code"); target.searchParams.delete("error"); target.searchParams.delete("state");
      target.searchParams.set("iss", origin);
      if (tx.state) target.searchParams.set("state", tx.state);
      if (params?.get("decision") === "deny") target.searchParams.set("error", "access_denied");
      else {
        const kind = params?.get("identity");
        if (kind !== "staff" && kind !== "reader") return failure(400, "invalid_request");
        let signedIn: Awaited<ReturnType<typeof identity>>;
        try { signedIn = await identity(request, kind); } catch { return failure(503, "temporarily_unavailable"); }
        if (!signedIn || signedIn.upstream_expiry <= Math.floor(Date.now() / 1000)) {
          const signIn = kind === "staff" ? '<p><a href="/newsroom" target="_blank" rel="noopener noreferrer">Sign in to the newsroom</a>, then return to this page.</p>' : (options.readerSignInAvailable === false || !options.readerSignIn) ? '<p>Reader authorization is unavailable on this console.</p>' : '<p><a href="/mcp/authorize?sign_in=reader">Sign in as a reader</a></p>';
          return new Response(`<!doctype html><html><head><meta charset="utf-8"><title>Sign in</title></head><body><main><h1>Sign in to continue</h1>${signIn}<p><a href="/mcp/authorize">Return to authorization</a></p></main></body></html>`, { status: 401, headers: { ...noStore, "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'", "Referrer-Policy": "same-origin" } });
        }
        try {
          const issued = await invoke({ operation: "issue", client: tx.client, redirect: tx.redirect, resource, challenge: tx.challenge, transaction_id: tx.csrf, ...signedIn });
          if (typeof issued.code !== "string") return failure(503, "temporarily_unavailable");
          target.searchParams.set("code", issued.code);
        } catch { return failure(503, "temporarily_unavailable"); }
      }
      return new Response(null, { status: 303, headers: { ...noStore, Location: target.href, "Set-Cookie": `${cookieName}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`, "Referrer-Policy": "no-referrer" } });
    },
    token: async (request: Request) => {
      const p = await form(request); if (!p) return failure(400, "invalid_request");
      const client = p.get("client_id") ?? "", grant = p.get("grant_type"), tokenResource = p.get("resource") ?? "";
      if (!Object.hasOwn(clients, client) || tokenResource !== resource || p.has("client_secret") || request.headers.has("authorization")) return failure(400, "invalid_request");
      let operation: Operation;
      if (grant === "authorization_code") {
        const redirect = p.get("redirect_uri") ?? "", verifier = p.get("code_verifier") ?? "", code = p.get("code") ?? "";
        if (!registered(client, redirect) || !/^[A-Za-z0-9._~-]{43,128}$/.test(verifier) || !code) return failure(400, "invalid_request");
        operation = { operation: "exchange", code, client, redirect, resource, verifier };
      } else if (grant === "refresh_token" && p.get("refresh_token")) operation = { operation: "refresh", token: p.get("refresh_token")!, client, resource };
      else return failure(400, "unsupported_grant_type");
      try { const result = await invoke(operation); return json(result, result.error ? 400 : 200); } catch { return failure(503, "temporarily_unavailable"); }
    },
    revoke: async (request: Request) => {
      const p = await form(request); const client = p?.get("client_id") ?? "", token = p?.get("token") ?? "";
      if (!p || !Object.hasOwn(clients, client) || !token || p.has("client_secret") || request.headers.has("authorization")) return failure(400, "invalid_request");
      try { await invoke({ operation: "revoke", token, client }); return new Response(null, { status: 200, headers: noStore }); } catch { return failure(503, "temporarily_unavailable"); }
    },
  };
}
