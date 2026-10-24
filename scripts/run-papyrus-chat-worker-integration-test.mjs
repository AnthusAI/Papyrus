import { build } from "esbuild";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const temporaryDirectory = await mkdtemp(join(process.cwd(), ".papyrus-chat-worker-integration-"));
try {
  const outputFile = join(temporaryDirectory, "test.mjs");
  await build({
    absWorkingDir: process.cwd(),
    entryPoints: ["scripts/test-papyrus-chat-worker-integration.ts"],
    outfile: outputFile,
    bundle: true,
    alias: {
      "chatticus/chat-server": join(process.cwd(), "node_modules/chatticus/conversation/src/http/embedded-chat-app.ts"),
      "chatticus/chat-worker": join(process.cwd(), "node_modules/chatticus/conversation/src/http/embedded-chat-worker.ts"),
      "@chatticus/host-protocol": join(process.cwd(), "node_modules/chatticus/host-protocol/src/schemas.ts"),
      "@chatticus/host-protocol/costs": join(process.cwd(), "node_modules/chatticus/host-protocol/src/costs.ts"),
      "@chatticus/host-protocol/edit-overlay": join(process.cwd(), "node_modules/chatticus/host-protocol/src/edit-overlay.ts"),
      "@chatticus/host-protocol/live-file-rules": join(process.cwd(), "node_modules/chatticus/host-protocol/src/live-file-rules.ts"),
      "@chatticus/host-protocol/live-files": join(process.cwd(), "node_modules/chatticus/host-protocol/src/live-files.ts"),
      "@chatticus/host-protocol/supervisor": join(process.cwd(), "node_modules/chatticus/host-protocol/src/supervisor.ts"),
      "@chatticus/host-protocol/workspace-edit": join(process.cwd(), "node_modules/chatticus/host-protocol/src/workspace-edit.ts"),
    },
    packages: "external",
    platform: "node",
    format: "esm",
    target: "node22",
  });
  await import(pathToFileURL(outputFile).href);
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
