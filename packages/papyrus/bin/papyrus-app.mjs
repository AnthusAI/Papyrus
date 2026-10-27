#!/usr/bin/env node
import path from "node:path";
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
  console.error("Usage: papyrus-app sync | papyrus-app brand diff <brand-id> [--papyrus <checkout>] | papyrus-app videoml-bundle [--preview]");
  process.exit(command ? 1 : 0);
}
