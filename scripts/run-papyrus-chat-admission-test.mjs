import { build } from "esbuild";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const temporaryDirectory = await mkdtemp(join(tmpdir(), "papyrus-chat-admission-"));
try {
  const outputFile = join(temporaryDirectory, "test.mjs");
  await build({
    absWorkingDir: process.cwd(),
    entryPoints: ["scripts/test-papyrus-chat-admission.ts"],
    outfile: outputFile,
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node22",
  });
  await import(pathToFileURL(outputFile).href);
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
