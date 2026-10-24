import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// Run the separate infrastructure package without pulling its newer CDK API
// into the root application's TypeScript compilation. The harness resolves all
// its CDK imports together, with or without that package's own dependencies.
const harness = fileURLToPath(new URL("../infra/amplify-app-shell/lib/cloud-email.test.ts", import.meta.url));
const result = spawnSync(process.execPath, ["--import", "tsx", harness, ...process.argv.slice(2)], {
  stdio: "inherit",
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
