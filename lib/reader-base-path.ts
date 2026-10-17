import { SITE_BRAND } from "./site-brand";

export function normalizeReaderBasePath(value: string | undefined | null): string {
  const trimmed = (value ?? "").trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

export function getReaderBasePath(): string {
  return normalizeReaderBasePath(SITE_BRAND.readerBasePath);
}

export function toPublicReaderPath(path: string, readerBasePath: string = getReaderBasePath()): string {
  if (!readerBasePath) return path;
  if (path === "/" || path === "") return readerBasePath;
  return `${readerBasePath}${path.startsWith("/") ? path : `/${path}`}`;
}

export function toInternalReaderPath(path: string, readerBasePath: string = getReaderBasePath()): string {
  if (!readerBasePath) return path;
  if (path === readerBasePath || path === `${readerBasePath}/`) return "/";
  if (path.startsWith(`${readerBasePath}/`)) return path.slice(readerBasePath.length);
  return path;
}
