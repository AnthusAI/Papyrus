import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// Run the separate infrastructure package's harness (same reason as test-infra-ci-gate.ts).
const harness = fileURLToPath(new URL("../infra/amplify-app-shell/lib/build-timeout.test.ts", import.meta.url));
const result = spawnSync(process.execPath, ["--import", "tsx", "--test", harness], { stdio: "inherit" });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
