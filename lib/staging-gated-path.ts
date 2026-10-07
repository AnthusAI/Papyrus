import { normalizeReaderBasePath } from "./reader-base-path";

function isStaticOrApiPath(pathname: string): boolean {
  return (
    pathname.startsWith("/_next")
    || pathname.startsWith("/api")
    || pathname === "/favicon.ico"
    || pathname.startsWith("/icon")
    || /\.[a-zA-Z0-9]+$/.test(pathname)
  );
}

export { isStaticOrApiPath };

export function isStagingGatedPath(pathname: string, readerBasePath: string = ""): boolean {
  if (isStaticOrApiPath(pathname)) return false;
  if (pathname === "/robots.txt") return false;
  if (pathname === "/newsroom" || pathname.startsWith("/newsroom/")) return false;
  const base = normalizeReaderBasePath(readerBasePath);
  if (base) return pathname === base || pathname.startsWith(`${base}/`);
  return true;
}
