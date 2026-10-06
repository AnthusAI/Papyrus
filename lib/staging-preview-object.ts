import { cookies } from "next/headers";
import { getUrl } from "aws-amplify/storage/server";
import { getAmplifyServerRuntime } from "./amplify-server-runtime";
import { getSiteEnv } from "./site-env";

export const PREVIEW_ROUTE_PREFIX = "/__preview";
export const PREVIEW_KEY_PREFIX = "preview/";

const PRESIGN_SECONDS = 60;
const NOT_FOUND_ERROR_NAMES = ["NotFound", "NoSuchKey"];
const PREVIEW_EXCLUDED_PREFIXES = ["/newsroom", "/api", "/_next", PREVIEW_ROUTE_PREFIX];

export function isStaticPreviewEnabled(environment: Record<string, string | undefined> = process.env): boolean {
  return getSiteEnv(environment) === "staging" && (environment.PAPYRUS_STAGING_PREVIEW ?? "").trim() === "static";
}

export function previewCandidateKeys(requestPath: string): string[] | null {
  if (requestPath.includes("//")) return null;
  let decoded: string;
  try {
    decoded = decodeURIComponent(requestPath);
  } catch {
    return null;
  }
  if (decoded.includes("//") || decoded.includes("\\") || decoded.includes("\0")) return null;
  const segments = decoded.split("/").filter((segment) => segment !== "");
  if (segments.some((segment) => segment === ".." || segment === ".")) return null;
  if (segments.length === 0) return [`${PREVIEW_KEY_PREFIX}index.html`];
  const joined = segments.join("/");
  if (decoded.endsWith("/")) return [`${PREVIEW_KEY_PREFIX}${joined}/index.html`];
  const base = `${PREVIEW_KEY_PREFIX}${joined}`;
  return [base, `${base}.html`, `${base}/index.html`];
}

export function shouldRewriteToPreview(pathname: string): boolean {
  if (pathname === "/favicon.ico" || pathname === "/robots.txt" || pathname.startsWith("/icon")) return false;
  return !PREVIEW_EXCLUDED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function isPreviewGatedPath(pathname: string): boolean {
  return shouldRewriteToPreview(pathname) || pathname === PREVIEW_ROUTE_PREFIX || pathname.startsWith(`${PREVIEW_ROUTE_PREFIX}/`);
}

export function previewRewritePathname(pathname: string): string {
  return `${PREVIEW_ROUTE_PREFIX}${pathname}`;
}

export function previewRequestPath(pathname: string): string {
  return pathname.slice(PREVIEW_ROUTE_PREFIX.length) || "/";
}

function isNotFoundError(error: unknown): boolean {
  const name = (error as { name?: string } | null)?.name ?? "";
  return NOT_FOUND_ERROR_NAMES.includes(name);
}

async function presignFirstExistingKey(candidateKeys: string[]): Promise<URL | null> {
  const { runWithAmplifyServerContext } = getAmplifyServerRuntime();
  return runWithAmplifyServerContext({
    nextServerContext: { cookies },
    operation: async (contextSpec) => {
      for (const key of candidateKeys) {
        try {
          const { url } = await getUrl(contextSpec, {
            path: key,
            options: { validateObjectExistence: true, expiresIn: PRESIGN_SECONDS },
          });
          return url;
        } catch (error) {
          if (!isNotFoundError(error)) throw error;
        }
      }
      return null;
    },
  });
}

function notFound(): Response {
  return new Response("Not found", { status: 404, headers: { "Cache-Control": "private, no-store" } });
}

export async function streamPreviewObject(pathname: string): Promise<Response> {
  if (!isStaticPreviewEnabled()) return notFound();
  const candidateKeys = previewCandidateKeys(previewRequestPath(pathname));
  if (!candidateKeys) return notFound();
  const presigned = await presignFirstExistingKey(candidateKeys);
  if (!presigned) return notFound();
  const upstream = await fetch(presigned);
  if (!upstream.ok || !upstream.body) return notFound();
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/octet-stream",
      "Cache-Control": "private, no-store",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}
