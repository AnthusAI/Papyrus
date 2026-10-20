#!/usr/bin/env tsx
// Every registered brand hard-codes one Kanbus editorial theme, and the whole newsroom renders inside that theme scope.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { DEFAULT_KANBUS_THEME, KANBUS_THEMES } from "@kanbus/ui";
import { FALLBACK_KANBUS_THEME, getKanbusTheme, getSiteBrand } from "../lib/site-brand.ts";

const EXPECTED_THEMES = {
  papyrus: "broadsheet-green",
  "anth-us": "newspaper-gothic",
  "pilobol-us": "refined-newsprint",
  "threat-intelligence": "night-desk",
};

function main() {
  const themeIds = KANBUS_THEMES.map((theme) => theme.id);
  assert.equal(FALLBACK_KANBUS_THEME, DEFAULT_KANBUS_THEME);
  assert.equal(DEFAULT_KANBUS_THEME, "newspaper-gothic");

  for (const [brandId, expected] of Object.entries(EXPECTED_THEMES)) {
    const brand = getSiteBrand(brandId);
    assert(themeIds.includes(brand.kanbusTheme), `${brandId} has kanbusTheme ${brand.kanbusTheme}, not one of ${themeIds.join(", ")}`);
    assert.equal(brand.kanbusTheme, expected, `${brandId} theme`);
    assert.equal(getKanbusTheme(brand), expected);
  }
  assert.equal(getKanbusTheme({} as never), DEFAULT_KANBUS_THEME, "a brand without a theme falls back to the default");

  const root = path.resolve(process.cwd());
  const read = (file: string) => fs.readFileSync(path.join(root, file), "utf8");
  const shell = read("components/newsroom-ops-shell.tsx");
  assert.match(shell, /className="newsroom-organizer" \{\.\.\.themeAttributes\}/, "theme scope is on the organizer root");
  assert.match(shell, /className="organizer-menu" \{\.\.\.themeAttributes\}/, "portaled menu carries the scope");
  assert.match(shell, /className="organizer-account-popup" \{\.\.\.themeAttributes\}/, "portaled account popup carries the scope");
  const board = read("components/newsroom-board-view.tsx");
  assert.doesNotMatch(board, /newsprint\.css|newsroom-newsprint-board|data-kanbus-theme=/);
  assert.equal(fs.existsSync(path.join(root, "components/newsroom-newsprint-board.css")), false);
  assert.match(read("components/newsroom-theme.tsx"), /styles\/themes\/index\.css/);
  const themeCss = read("components/newsroom-theme.css");
  for (const token of ["paper", "sidebar", "ink", "muted", "rule", "accent", "on-accent", "title-font", "ui-font", "mono-font"]) {
    assert.match(themeCss, new RegExp(`--kb-theme-${token}\\b`), `--kb-theme-${token} feeds the shell`);
  }
  for (const id of themeIds) assert(fs.existsSync(path.join(root, `components/newsroom-theme-fonts/${id}.css`)), `fonts for ${id}`);
  for (const file of ["publications/anth_us/theme.css", "publications/pilobol_us/theme.css", "publications/threat_intelligence/theme.css"]) {
    const css = read(file);
    assert.doesNotMatch(css, /papyrus-newsprint-board|\.issue-card|\.kb-column-header|\.kb-issue-detail/, `${file} must not restyle Kanbus internals`);
  }
  console.log("kanbus theme tests passed");
}

main();
