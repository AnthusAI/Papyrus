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
    packages: "external",
    platform: "node",
    format: "esm",
    target: "node22",
  });
  await import(pathToFileURL(outputFile).href);
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
