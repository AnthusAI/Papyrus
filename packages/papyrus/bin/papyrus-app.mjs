#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { sync } from "../src/sync.mjs";

const [command, ...rest] = process.argv.slice(2);
if (command === "sync") {
  sync();
} else if (command === "brand" && rest[0] === "diff") {
  const { brandDiff } = await import("../src/brand.mjs");
  const flag = rest.indexOf("--papyrus");
  const checkout = flag === -1 ? undefined : rest[flag + 1];
  try {
    process.exit(brandDiff({ id: rest[1], checkout: checkout && path.resolve(checkout) }).drifted ? 1 : 0);
  } catch (error) {
    console.error(error.message);
    process.exit(2);
  }
} else if (command === "alexa-sync") {
  // Runs in the site's Amplify build after the backend deploy: creates or updates the site's Alexa skill (docs/alexa.md).
  // The package ships the compiled cli.js next to cli.ts; a checkout without it runs the TypeScript through tsx.
  const compiled = fileURLToPath(new URL("../amplify/plugins/alexa/sync/cli.js", import.meta.url));
  const source = fileURLToPath(new URL("../amplify/plugins/alexa/sync/cli.ts", import.meta.url));
  const result = existsSync(compiled)
    ? spawnSync(process.execPath, [compiled, ...rest], { stdio: "inherit" })
    : spawnSync("npx", ["--yes", "tsx", source, ...rest], { stdio: "inherit" });
  process.exit(result.status ?? 1);
} else if (command === "videoml-bundle") {
  const preview = rest.includes("--preview");
  const { buildBrowserBundle } = await import("../scripts/videoml/build-browser-bundle.mjs");
  const { buildPreviewBundle } = await import("../scripts/videoml/build-preview-bundle.mjs");
  try {
    await (preview ? buildPreviewBundle() : buildBrowserBundle());
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
} else {
  console.error("Usage: papyrus-app sync | papyrus-app brand diff <brand-id> [--papyrus <checkout>] | papyrus-app alexa-sync [--outputs FILE] | papyrus-app videoml-bundle [--preview]");
  process.exit(command ? 1 : 0);
}
