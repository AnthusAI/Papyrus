import type { NextRequest } from "next/server";
import { resolveNewsroomChatIdentity, type NewsroomChatIdentityResolver } from "../newsroom-chat-identity";
import { createCommonsSource, userAgent } from "./commons";
import { MAXIMUM_PICTURE_BYTES, PictureRefused, readPicture } from "./picture";
import { SourceBusy, SourceFailure, type StockCandidate, type StockImageSource } from "./types";

/**
 * The editor-only route behind the cover picker: `POST /api/newsroom/stock-images`, a Node route of the newsroom's Next server (the
 * same place the other `/api/newsroom/*` routes run), not a Lambda of its own and not the browser. Wikimedia sees the server's address and
 * User-Agent, never an editor's.
 *
 * Who may call: a Cognito access token in `Authorization: Bearer`, verified against the site's user pool, with the `editor` or `admin` group
 * (`resolveNewsroomChatIdentity`, the same check the private chat route uses). No new auth rule, no cookie, no anonymous path.
 *
 * Three actions, all `{ action, ... }` JSON:
 * - `search { target, cursor, exclude[] }` -> up to four allowed candidates and the next cursor.
 * - `lookup { id }` -> the candidate looked up again at the source, so the licence record we store is the source's current answer.
 * - `image { id }` -> the picture's bytes, taken from the address the source gave for that id (never an address the browser names), checked
 *   like `reference_thumbnails.py` checks a thumbnail, with the width, height and an opaque `x-stock-picked-by` account id in headers.
 */
export const BATCH_SIZE = 4;
export const MAXIMUM_EXCLUDED = 400;
const NO_STORE = { "cache-control": "no-store", "x-content-type-options": "nosniff" };
const FETCH_TIMEOUT_MILLISECONDS = 20_000;
const MAXIMUM_REDIRECTS = 2;

export type StockImageRouteOptions = {
  resolveIdentity?: NewsroomChatIdentityResolver;
  source?: StockImageSource;
  fetcher?: (url: string, init: { headers: Record<string, string>; redirect: "manual"; signal: AbortSignal }) => Promise<Response>;
  contact?: string;
};

function json(body: unknown, status = 200, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...NO_STORE, "content-type": "application/json", ...extra } });
}

function failure(status: number, message: string, extra: Record<string, string> = {}): Response {
  return json({ error: message }, status, extra);
}

let sharedSource: StockImageSource | undefined;

async function boundedBody(response: Response): Promise<Uint8Array | null> {
  const declared = Number(response.headers.get("content-length") ?? "0");
  if (declared > MAXIMUM_PICTURE_BYTES) return null;
  const reader = response.body?.getReader();
  if (!reader) return null;
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAXIMUM_PICTURE_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let at = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, at);
    at += chunk.byteLength;
  }
  return bytes;
}

async function fetchPicture(candidate: StockCandidate, source: StockImageSource, options: StockImageRouteOptions): Promise<Uint8Array> {
  const fetcher = options.fetcher ?? ((url, init) => fetch(url, init));
  let address = candidate.imageUrl;
  for (let hop = 0; hop <= MAXIMUM_REDIRECTS; hop += 1) {
    const parsed = new URL(address);
    if (parsed.protocol !== "https:" || !source.imageHosts.includes(parsed.hostname)) throw new SourceFailure("The picture is not at an address this source may be copied from.");
    const response = await fetcher(address, {
      headers: { "user-agent": userAgent(options.contact ?? process.env.PAPYRUS_WIKIMEDIA_CONTACT), accept: "image/jpeg,image/png,image/webp" },
      redirect: "manual",
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MILLISECONDS),
    });
    if (response.status >= 300 && response.status < 400) {
      const next = response.headers.get("location");
      if (!next) throw new SourceFailure("The source redirected without saying where.");
      address = new URL(next, address).toString();
      continue;
    }
    if (response.status === 429 || response.status === 503) {
      const retry = Number.parseInt(response.headers.get("retry-after") ?? "", 10);
      throw new SourceBusy(Number.isFinite(retry) ? retry : null);
    }
    if (!response.ok) throw new SourceFailure(`The source answered ${response.status} for the picture.`);
    const bytes = await boundedBody(response);
    if (!bytes) throw new PictureRefused("The image is too large to copy in.");
    return bytes;
  }
  throw new SourceFailure("The source redirected too many times.");
}

export async function handleStockImageRequest(request: NextRequest | Request, options: StockImageRouteOptions = {}): Promise<Response> {
  if (request.method !== "POST") return failure(405, "Use POST.", { allow: "POST" });
  let identity;
  try {
    identity = await (options.resolveIdentity ?? resolveNewsroomChatIdentity)(request as NextRequest);
  } catch {
    return failure(503, "Sign-in could not be checked right now. Try again shortly.");
  }
  if (!identity?.subject) return failure(401, "Sign in as an editor to find images.");

  let body: Record<string, unknown>;
  try {
    const parsed = await request.json();
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
    body = parsed as Record<string, unknown>;
  } catch {
    return failure(400, "That request could not be understood.");
  }

  const source = options.source ?? (sharedSource ??= createCommonsSource({ contact: options.contact }));
  try {
    if (body.action === "search") {
      const target = typeof body.target === "string" ? body.target : "";
      const cursor = typeof body.cursor === "string" ? body.cursor : "";
      const exclude = Array.isArray(body.exclude) ? body.exclude.filter((id): id is string => typeof id === "string").slice(0, MAXIMUM_EXCLUDED) : [];
      if (!target.trim()) return failure(400, "Say what to look for.");
      const result = await source.search({ target, cursor, exclude: new Set(exclude), count: BATCH_SIZE });
      return json({ source: source.id, sourceLabel: source.label, candidates: result.candidates, nextCursor: result.nextCursor });
    }
    if (body.action === "lookup" || body.action === "image") {
      const id = typeof body.id === "string" ? body.id : "";
      const candidate = id ? await source.lookup(id) : null;
      if (!candidate) return failure(404, "That image is no longer available with a licence we can use. Choose another.");
      if (body.action === "lookup") return json({ candidate });
      const bytes = await fetchPicture(candidate, source, options);
      const picture = readPicture(bytes);
      return new Response(bytes as BodyInit, {
        status: 200,
        headers: {
          ...NO_STORE,
          "content-type": picture.mediaType,
          "content-length": String(bytes.byteLength),
          "x-stock-width": String(picture.width),
          "x-stock-height": String(picture.height),
          "x-stock-picked-by": identity.subject,
        },
      });
    }
    return failure(400, "That request could not be understood.");
  } catch (error) {
    if (error instanceof SourceBusy) {
      return failure(503, error.message, error.retryAfterSeconds === null ? {} : { "retry-after": String(error.retryAfterSeconds) });
    }
    if (error instanceof PictureRefused) return failure(422, error.message);
    if (error instanceof SourceFailure) return failure(502, error.message);
    return failure(502, "The image source could not be reached. Try again shortly.");
  }
}
