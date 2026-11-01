import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// Run the separate infrastructure package's harness (same reason as test-infra-chat.ts).
const harness = fileURLToPath(new URL("../infra/amplify-app-shell/lib/ci-gate.test.ts", import.meta.url));
const result = spawnSync(process.execPath, ["--import", "tsx", harness], { stdio: "inherit" });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
