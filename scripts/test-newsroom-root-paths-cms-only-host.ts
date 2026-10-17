import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";

test("newsroom root paths on a CMS-only host", () => {
  const result = spawnSync(process.execPath, ["--import", "tsx", "scripts/test-newsroom-root-paths.ts"], {
    env: { ...process.env, PAPYRUS_SITE_BRAND: "pilobol-us" },
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
