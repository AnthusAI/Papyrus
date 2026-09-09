import { SITE_BRAND } from "./site-brand";

const DEFAULT_NEWSROOM_BASE_PATH = "/newsroom";

/** Internal Next.js route prefix (always `/newsroom/...`). */
export function getInternalNewsroomBasePath(): string {
  return DEFAULT_NEWSROOM_BASE_PATH;
}

/** Public browser path prefix (`""` on a CMS-only newsroom subdomain). */
export function getPublicNewsroomBasePath(): string {
  return SITE_BRAND.newsroomBasePath ?? DEFAULT_NEWSROOM_BASE_PATH;
}

export function usesNewsroomRootPaths(): boolean {
  return getPublicNewsroomBasePath() === "";
}

export function toPublicNewsroomPath(internalPath: string): string {
  const publicBase = getPublicNewsroomBasePath();
  if (publicBase !== "") return internalPath;
  if (internalPath === "/newsroom" || internalPath === "/newsroom/") return "/";
  if (internalPath.startsWith("/newsroom/")) {
    return internalPath.slice("/newsroom".length) || "/";
  }
  return internalPath;
}

export function toInternalNewsroomPath(publicPath: string): string {
  const publicBase = getPublicNewsroomBasePath();
  const normalized = publicPath.startsWith("/") ? publicPath : `/${publicPath}`;
  if (publicBase !== "") {
    if (normalized === publicBase || normalized === `${publicBase}/`) return "/newsroom";
    if (normalized.startsWith(`${publicBase}/`)) return normalized;
    if (normalized.startsWith("/newsroom")) return normalized;
    return `/newsroom${normalized === "/" ? "" : normalized}`;
  }
  if (normalized === "/" || normalized === "") return "/newsroom";
  if (normalized.startsWith("/newsroom")) return normalized;
  return `/newsroom${normalized}`;
}

export function newsroomHref(...segments: string[]): string {
  const suffix = segments.filter(Boolean).join("/");
  const publicBase = getPublicNewsroomBasePath();
  if (!suffix) return publicBase || "/";
  return publicBase ? `${publicBase}/${suffix}` : `/${suffix}`;
}
