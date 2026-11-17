/**
 * Synthesizes the real backend in the bootstrap stage (`PAPYRUS_BOOTSTRAP_STAGE=1`) in a child process, because Amplify
 * allows one backend per process, and counts every resource across the root and nested templates. Shared by
 * `test-bootstrap-stage.ts` and `test-agents-stack.ts`.
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

export const CLOUDFORMATION_OPERATION_LIMIT = 2500;
// Headroom for plugins and features a site turns on, and for models added later. Not raised by any slice.
export const BOOTSTRAP_BUDGET = 2000;

export type BootstrapStageMeasure = { resources: number; modelStacks: string[]; templates: string[] };

export function measureBootstrapStage(): BootstrapStageMeasure {
  const outputDirectory = mkdtempSync(path.join(tmpdir(), "papyrus-bootstrap-"));
  try {
    const synth = spawnSync("npx", ["tsx", "scripts/synth-site-backend.mts", outputDirectory, '{"productionAppId":"","brandId":"bootstrap-test"}'], {
      cwd: path.resolve(import.meta.dirname, ".."),
      env: { ...process.env, PAPYRUS_BOOTSTRAP_STAGE: "1" },
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
    });
    assert.equal(synth.status, 0, `${synth.stdout}\n${synth.stderr}`);

    let resources = 0;
    const modelStacks: string[] = [];
    const templates = readdirSync(outputDirectory).filter((name) => name.endsWith(".template.json"));
    for (const file of templates) {
      resources += Object.keys(JSON.parse(readFileSync(path.join(outputDirectory, file), "utf8")).Resources ?? {}).length;
      const model = /PapyrusCmsApi(.+?)[0-9A-F]{8}\.nested\.template\.json$/.exec(file);
      if (model) modelStacks.push(model[1]);
    }
    return { resources, modelStacks, templates };
  } finally {
    rmSync(outputDirectory, { recursive: true, force: true });
  }
}
