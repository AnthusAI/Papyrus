import type { MetadataRoute } from "next";
import { isIndexable } from "../lib/site-env";

export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  if (isIndexable()) {
    return { rules: { userAgent: "*", allow: "/" } };
  }
  return { rules: { userAgent: "*", disallow: "/" } };
}
