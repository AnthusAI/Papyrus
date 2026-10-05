#!/usr/bin/env node
import { sync } from "../src/sync.mjs";

const [command] = process.argv.slice(2);
if (command === "sync") {
  sync();
} else {
  console.error("Usage: papyrus-app sync");
  process.exit(command ? 1 : 0);
}
