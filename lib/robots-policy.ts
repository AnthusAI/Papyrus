import type { MetadataRoute } from "next";
import { getRootRoute, getSiteBrand } from "./site-brand";
import { isIndexable } from "./site-env";

const DISALLOW_ALL: MetadataRoute.Robots = { rules: { userAgent: "*", disallow: "/" } };
const ALLOW_ALL: MetadataRoute.Robots = { rules: { userAgent: "*", allow: "/" } };

export function buildRobots(
  environment: Record<string, string | undefined> = process.env,
  brand = getSiteBrand(),
): MetadataRoute.Robots {
  if (getRootRoute(brand).kind === "newsroom") return DISALLOW_ALL;
  return isIndexable(environment) ? ALLOW_ALL : DISALLOW_ALL;
}
