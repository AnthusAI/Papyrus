#!/usr/bin/env node
import { sync } from "../src/sync.mjs";

const [command, ...rest] = process.argv.slice(2);
if (command === "sync") {
  sync();
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
  console.error("Usage: papyrus-app sync | papyrus-app videoml-bundle [--preview]");
  process.exit(command ? 1 : 0);
}
