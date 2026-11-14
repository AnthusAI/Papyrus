import { normalizeReaderBasePath } from "./reader-base-path";

function isStaticOrApiPath(pathname: string): boolean {
  return (
    pathname.startsWith("/_next")
    || pathname.startsWith("/api")
    // `papyrus login --remote` approval pages (lib/cli-login-pages.ts): served at the site root, never under /newsroom.
    || pathname === "/cli/approve"
    || pathname === "/cli/callback"
    || pathname === "/cli/enroll"
    || pathname === "/cli/challenge"
    || pathname === "/favicon.ico"
    || pathname.startsWith("/icon")
    || /\.[a-zA-Z0-9]+$/.test(pathname)
  );
}

export { isStaticOrApiPath };

export function isStagingGatedPath(pathname: string, readerBasePath: string = "", newsroomAtRoot: boolean = false): boolean {
  if (newsroomAtRoot) return false;
  if (isStaticOrApiPath(pathname)) return false;
  if (pathname === "/robots.txt") return false;
  if (pathname === "/newsroom" || pathname.startsWith("/newsroom/")) return false;
  const base = normalizeReaderBasePath(readerBasePath);
  if (base) return pathname === base || pathname.startsWith(`${base}/`);
  return true;
}
