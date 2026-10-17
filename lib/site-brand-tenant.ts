import path from "node:path";
import { getSiteBrand, resolveSiteBrandId, type SiteBrand, type SiteBrandId } from "./site-brand";

export function resolveActiveSiteBrand(brandId?: SiteBrandId): SiteBrand {
  return getSiteBrand(brandId ?? resolveSiteBrandId());
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
