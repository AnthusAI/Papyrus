import path from "node:path";
import {
  getSiteBrand,
  resolveRuntimeSiteBrandId,
  resolveSiteBrandId,
  type SiteBrand,
  type SiteBrandId,
} from "./site-brand";

export const BRAND_OVERRIDE_COOKIE = "papyrus-site-brand-override";

export function resolveActiveSiteBrandId(
  cookieOverride: string | undefined | null = null,
  envBrandId: SiteBrandId = resolveSiteBrandId(),
): SiteBrandId {
  return resolveRuntimeSiteBrandId(cookieOverride) ?? envBrandId;
}

export function resolveActiveSiteBrand(
  cookieOverride: string | undefined | null = null,
  brandId?: SiteBrandId,
): SiteBrand {
  const resolvedId = brandId ?? resolveActiveSiteBrandId(cookieOverride);
  return getSiteBrand(resolvedId);
}

export function resolveBrandConfigPath(relativePath: string): string {
  return path.isAbsolute(relativePath) ? relativePath : path.join(process.cwd(), relativePath);
}

export function getBrandSteeringConfigPath(brand: SiteBrand = resolveActiveSiteBrand()): string {
  return resolveBrandConfigPath(brand.steeringConfigPath);
}

export function getBrandNewsroomSectionsConfigPath(brand: SiteBrand = resolveActiveSiteBrand()): string {
  return resolveBrandConfigPath(brand.newsroomSectionsConfigPath);
}

export function getBrandAnalysisProfilesPath(brand: SiteBrand = resolveActiveSiteBrand()): string {
  return resolveBrandConfigPath(brand.analysisProfilesPath);
}
