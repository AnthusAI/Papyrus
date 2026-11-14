// Resolves the optional backend features for an environment, and checks a site.json's cms.environment, and prints the outcome as JSON.
// Used by features_backend/optional-features-off.feature. Input: {"environment": {...}, "features": {...}?, "site": {...}?} where "site" is an example file name
// and its cms.environment is extended with "environment".
import fs from "node:fs";
import path from "node:path";
import { assertFeaturePrerequisites, resolveSiteBackendFeatureFlags } from "../amplify/site-backend-names";
import { parseSiteConfig } from "../infra/amplify-app-shell/lib/site-config";

const input = JSON.parse(process.argv[2] ?? "{}") as { environment?: Record<string, string>; features?: Record<string, boolean>; site?: string };
const identity = { brandId: "papyrus", amplifyAppId: "app", amplifyBranch: "main", productionAppId: "app" };
try {
  if (input.site) {
    const raw = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../infra/amplify-app-shell/examples", input.site), "utf8"));
    Object.assign(raw.cms.environment, input.environment ?? {});
    parseSiteConfig(raw);
    console.log(JSON.stringify({ ok: true }));
  } else {
    const flags = resolveSiteBackendFeatureFlags(input.features, input.environment ?? {}, identity);
    assertFeaturePrerequisites(flags, input.environment ?? {});
    console.log(JSON.stringify({ ok: true, flags }));
  }
} catch (error) {
  console.log(JSON.stringify({ ok: false, error: (error as Error).message }));
}
