import path from "node:path";
import { getSiteBrand, resolveSiteBrandId, type SiteBrand, type SiteBrandId } from "./site-brand";

export function resolveActiveSiteBrand(brandId?: SiteBrandId): SiteBrand {
  return getSiteBrand(brandId ?? resolveSiteBrandId());
}

export function resolveBrandConfigPath(relativePath: string): string {
  return path.isAbsolute(relativePath) ? relativePath : path.join(process.cwd(), relativePath);
}

/** Optional repo files a brand may still name; undefined means the site keeps that configuration as backend data and nothing is looked up. */
function optionalBrandConfigPath(relativePath: string | undefined): string | undefined {
  return relativePath ? resolveBrandConfigPath(relativePath) : undefined;
}

export function getBrandSteeringConfigPath(brand: SiteBrand = resolveActiveSiteBrand()): string | undefined {
  return optionalBrandConfigPath(brand.steeringConfigPath);
}

export function getBrandNewsroomSectionsConfigPath(brand: SiteBrand = resolveActiveSiteBrand()): string | undefined {
  return optionalBrandConfigPath(brand.newsroomSectionsConfigPath);
}

export function getBrandAnalysisProfilesPath(brand: SiteBrand = resolveActiveSiteBrand()): string | undefined {
  return optionalBrandConfigPath(brand.analysisProfilesPath);
}
