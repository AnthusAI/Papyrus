import { getUrl } from "aws-amplify/storage/server";
import { getAmplifyServerRuntime } from "./amplify-server-runtime";

const STORAGE_URL_EXPIRES_IN_SECONDS = 60 * 60;
const STORAGE_URL_CACHE_TTL_MS = 55 * 60 * 1000;
const GUEST_READ_PREFIX = "media/";

type SignedUrlCacheEntry = {
  expiresAt: number;
  url: string;
};

const signedUrlCache = new Map<string, SignedUrlCacheEntry>();

export function isGuestReadableStoragePath(storagePath: string): boolean {
  const normalized = storagePath.trim().replace(/^\/+/, "");
  return normalized.startsWith(GUEST_READ_PREFIX);
}

export function buildReaderMediaProxyUrl(storagePath: string): string {
  const normalized = storagePath.trim().replace(/^\/+/, "");
  if (!isGuestReadableStoragePath(normalized)) {
    throw new Error(`Storage path is not reader-public: ${storagePath}`);
  }
  return `/api/media/${normalized.split("/").map((segment) => encodeURIComponent(segment)).join("/")}`;
}

export async function resolveReaderStorageUrl(storagePath: string): Promise<string> {
  const normalized = storagePath.trim().replace(/^\/+/, "");
  if (!normalized) {
    throw new Error("Missing storage path.");
  }
  if (isGuestReadableStoragePath(normalized)) {
    return buildReaderMediaProxyUrl(normalized);
  }
  return signStorageUrl(normalized);
}

export async function signStorageUrl(storagePath: string): Promise<string> {
  const normalized = storagePath.trim().replace(/^\/+/, "");
  const cached = signedUrlCache.get(normalized);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.url;
  }

  const { runWithAmplifyServerContext } = getAmplifyServerRuntime();
  const result = await runWithAmplifyServerContext({
    nextServerContext: null,
    operation: (contextSpec) =>
      getUrl(contextSpec, {
        path: normalized,
        options: {
          expiresIn: STORAGE_URL_EXPIRES_IN_SECONDS,
        },
      }),
  });
  const url = result.url.toString();
  signedUrlCache.set(normalized, {
    expiresAt: Date.now() + STORAGE_URL_CACHE_TTL_MS,
    url,
  });
  return url;
}
