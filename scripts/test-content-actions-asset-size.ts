import assert from "node:assert/strict";
import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { bundleFromCheckout } from "../amplify/functions/shared/python-bundle";
import { contentActionsRequirements } from "../amplify/functions/content-actions/resource";

const LIMIT_BYTES = 100 * 1024 * 1024;

function directoryBytes(directory: string): number {
  let total = 0;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name);
    total += entry.isDirectory() ? directoryBytes(entryPath) : fs.statSync(entryPath).size;
  }
  return total;
}

const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), "content-actions-asset-"));
try {
  bundleFromCheckout(outputDir, {
    functionDir: "content-actions",
    modules: ["papyrus_content"],
    requirements: contentActionsRequirements,
    checkoutExtras: (directory) => {
      execSync(
        `python3 -m pip install -r amplify/functions/content-actions/requirements.txt -t "${directory}" --no-cache-dir --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 --only-binary=:all: --ignore-requires-python`,
        { stdio: "inherit" },
      );
    },
  });
  const bytes = directoryBytes(outputDir);
  console.log(`content-actions asset: ${(bytes / 1024 / 1024).toFixed(1)} MB`);
  assert.ok(fs.existsSync(path.join(outputDir, "handler.py")));
  assert.ok(bytes < LIMIT_BYTES, `asset is ${bytes} bytes, limit ${LIMIT_BYTES}`);
} finally {
  fs.rmSync(outputDir, { recursive: true, force: true });
}
