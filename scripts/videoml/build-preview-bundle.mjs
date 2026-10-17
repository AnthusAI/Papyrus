#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  bundleVideoEntries,
  loadBrandVideoSlot,
  previewEntryPath,
  previewHtmlTemplatePath,
  standardEntryPath,
} from "./bundle-common.mjs";

const REACT_18_VERSION = "18.3.1";
const VENDOR_FILES = {
  "react.production.min.js": `https://unpkg.com/react@${REACT_18_VERSION}/umd/react.production.min.js`,
  "react-dom.production.min.js": `https://unpkg.com/react-dom@${REACT_18_VERSION}/umd/react-dom.production.min.js`,
};

async function ensureReactVendor(outDirectory) {
  const vendorDirectory = path.join(outDirectory, "vendor");
  fs.mkdirSync(vendorDirectory, { recursive: true });
  for (const [name, url] of Object.entries(VENDOR_FILES)) {
    const target = path.join(vendorDirectory, name);
    if (fs.existsSync(target)) continue;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Failed to download ${url}: ${response.status} ${response.statusText}`);
    fs.writeFileSync(target, Buffer.from(await response.arrayBuffer()));
  }
}

export async function buildPreviewBundle(projectRoot = process.cwd(), env = process.env) {
  const { brandId, bundleEntry } = await loadBrandVideoSlot(projectRoot, env);
  const outDirectory = path.join(projectRoot, "public/videoml");
  await ensureReactVendor(outDirectory);
  fs.copyFileSync(previewHtmlTemplatePath, path.join(outDirectory, "preview.html"));
  const result = await bundleVideoEntries({
    projectRoot,
    entries: [standardEntryPath, previewEntryPath, bundleEntry],
    outfile: path.join(outDirectory, "preview-bundle.js"),
  });
  console.error(`VideoML preview bundle for '${brandId}': ${result.outfile} (${result.size} bytes)`);
  return result;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  buildPreviewBundle().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
