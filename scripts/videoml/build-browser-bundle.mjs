#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundleVideoEntries, loadBrandVideoSlot, standardEntryPath } from "./bundle-common.mjs";

export async function buildBrowserBundle(projectRoot = process.cwd(), env = process.env) {
  const { brandId, bundleEntry } = await loadBrandVideoSlot(projectRoot, env);
  const result = await bundleVideoEntries({
    projectRoot,
    entries: [standardEntryPath, bundleEntry],
    outfile: path.join(projectRoot, "public/videoml/browser-bundle.js"),
  });
  console.error(`VideoML browser bundle for '${brandId}': ${result.outfile} (${result.size} bytes)`);
  return result;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  buildBrowserBundle().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
