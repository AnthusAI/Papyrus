import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";

// tsx compiles JSX with the classic runtime here; Next supplies the automatic one in the app.
(globalThis as { React?: typeof React }).React = React;
async function main() {
  const { AnthUsLogo, AnthUsLogoCompact } = await import("../publications/anth_us/logo");
  const { anthUsBrand } = await import("../publications/anth_us/brand");

  // The anth-us pack provides both marks; the compact one is the tile and "A" without the lettering.
  assert.equal(anthUsBrand.components?.NewsroomLogo, AnthUsLogo);
  assert.equal(anthUsBrand.components?.NewsroomLogoCompact, AnthUsLogoCompact);
  const full = renderToStaticMarkup(React.createElement(AnthUsLogo, { className: "organizer-brand-logo" }));
  const compact = renderToStaticMarkup(React.createElement(AnthUsLogoCompact, { className: "organizer-masthead-logo" }));
  assert.match(full, /anth-us-logo-word/);
  assert.doesNotMatch(compact, /anth-us-logo-word/);
  for (const part of ["anth-us-logo-tile", "anth-us-logo-a"]) assert.match(compact, new RegExp(part));
  assert.match(compact, /aria-label="Anthus"/);
  assert.match(compact, /class="organizer-masthead-logo"/);

  // The mobile top bar masthead prefers the compact mark, then the full logo; the serif title is the no-logo fallback.
  const shell = fs.readFileSync(path.join(process.cwd(), "components/newsroom-ops-shell.tsx"), "utf8");
  assert.match(shell, /MastheadLogo = SITE_BRAND\.components\?\.NewsroomLogoCompact \?\? SITE_BRAND\.components\?\.NewsroomLogo/);
  assert.match(shell, /className="organizer-masthead"[^>]*>\{MastheadLogo \? <MastheadLogo className="organizer-masthead-logo" \/> : appTitle\}/);

  // Scaled fallback and the desktop rule that hides the masthead while the sidebar shows the logo.
  const css = fs.readFileSync(path.join(process.cwd(), "components/newsroom-organizer.css"), "utf8");
  assert.match(css, /\.organizer-masthead-logo\{[^}]*max-width:36vw/);
  assert.match(css, /min-width:901px\)\{\.newsroom-organizer\[data-sidebar-collapsed=false\] \.organizer-masthead\{display:none\}/);
  // The brand's masthead rule must not set display, or it would override that desktop rule.
  const theme = fs.readFileSync(path.join(process.cwd(), "publications/anth_us/theme.css"), "utf8");
  const mastheadRule = theme.match(/\.newsroom-organizer :is\(\.organizer-brand, \.organizer-masthead\) \{[^}]*\}/);
  assert(mastheadRule, "logo tokens apply to the masthead");
  assert.doesNotMatch(mastheadRule[0], /display/);
  console.log("PASS the brand logotype shows on the mobile newsroom bar");
}
void main();
