#!/usr/bin/env node
/**
 * Brand/theme assertions for the Anth.us publication.
 *
 * Deliberately a sibling of `scripts/test-theme-packs.cjs` rather than extra
 * assertions inside it: that script currently fails on an unrelated,
 * pre-existing assertion (line 33 expects `normalizeSiteBrandId("pilobol")`
 * to be `null`, but `lib/site-brand.ts` has mapped `pilobol` to `pilobol-us`
 * for a while). `node:assert` aborts the file on first failure, so anything
 * appended there would never run. Fold these back in once that is resolved.
 */

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

require("./register-papyrus-aliases.cjs");
registerTypeScriptRequire();

const {
  getSiteBrand,
  getRootRoute,
  normalizeSiteBrandId,
  resolveSiteBrandId,
} = require("../lib/site-brand.ts");
const { getSiteStack, ANTH_US_THEME_PACK_TOKENS } = require("../lib/site-stack.ts");

// --- brand resolution -----------------------------------------------------

assert.equal(resolveSiteBrandId("anth-us"), "anth-us");
assert.equal(normalizeSiteBrandId("anth-us"), "anth-us");
assert.equal(normalizeSiteBrandId("anth.us"), null);
assert.equal(normalizeSiteBrandId("anth_us"), null);
assert.equal(normalizeSiteBrandId("ANTH-US"), null);
assert.equal(normalizeSiteBrandId("anthus"), null);
assert.equal(normalizeSiteBrandId("pilobolus"), null);

// --- brand values, all traceable to the live Gatsby site ------------------

const anthus = getSiteBrand("anth-us");
assert.equal(anthus.id, "anth-us");
assert.equal(anthus.appTitle, "Anthus");
assert.equal(anthus.publicationName, "Anthus");
assert.equal(anthus.mastheadTitle, "Anthus");
assert.equal(anthus.articleTitleSuffix, "Anthus");
assert.equal(anthus.placeholderByline, "Ryan Porter");
assert.match(anthus.appDescription, /self-aligning AI systems/);
assert.match(anthus.textFont, /Montserrat/);
assert.equal(anthus.themePack, "anth-us");
assert.equal(anthus.opsChrome, "app");
assert.equal(anthus.renderer.kind, "markus");
assert.equal(anthus.hosting.kind, "amplify-ssr");
assert.equal(anthus.corpusKey, "anth-us");
assert.equal(anthus.steeringConfigPath, "corpora/anth-us-steering.yml");
assert.deepEqual(getRootRoute(anthus), { kind: "newsroom" });

// --- staging deployment: repository only, no live host --------------------

assert.equal(anthus.readerDeployment?.kind, "amplify-static");
assert.equal(
  anthus.readerDeployment?.repository,
  "https://github.com/AnthusAI/Anth.us-Papyrus",
);
// Production anth.us still serves the Gatsby site. Asserting these stay unset
// is the point: a canonical host must not be claimed before cutover.
assert.equal(anthus.readerDeployment?.domain, undefined);
assert.equal(anthus.readerDeployment?.amplifyAppId, undefined);

// Also check the source text, with comments stripped -- the file explains in
// prose *why* a domain is not set, so the prose would otherwise match.
const brandCode = fs
  .readFileSync(path.join(process.cwd(), "publications/anth_us/brand.ts"), "utf8")
  .replace(/^\s*\/\/.*$/gm, "");
assert.doesNotMatch(brandCode, /domain:\s*["'`]/);
assert.doesNotMatch(brandCode, /amplifyAppId:\s*["'`]/);

// No DNS / custom-domain wiring for Anthus anywhere in the repo's own config.
assert.doesNotMatch(brandCode, /domainAssociation|customDomain|route53|hostedZone/i);

// --- theme tokens ---------------------------------------------------------

assert.deepEqual(anthus.themeTokens, ANTH_US_THEME_PACK_TOKENS);
assert.equal(anthus.themeTokens.paper, "#f1f9fe"); // --color-layout-bg
assert.equal(anthus.themeTokens.card, "#ffffff"); // --color-wrapper-bg
assert.equal(anthus.themeTokens.ink, "#333333"); // --color-text
assert.equal(anthus.themeTokens.moss, "#dc5497"); // --color-primary
assert.equal(anthus.themeTokens.ochre, "#ff57b4"); // --color-active
assert.equal(anthus.themeTokens.quote, "#9b165d"); // --color-gradient-mid
assert.equal(anthus.themeTokens.tip, "#0389d7"); // --color-gradient-end
assert.equal(anthus.themeTokens.stage, "#fedded"); // --color-hamburger
assert.equal(anthus.themeTokens.line, "#cccccc"); // derived: hr over white
assert.equal(anthus.themeTokens.muted, "#5f6b73"); // derived: no such token upstream
assert.equal(anthus.themeTokens.caution, "#e95800");

// The source site has no dark mode; do not invent one.
assert.equal(anthus.themeTokens.dark, undefined);

const papyrus = getSiteBrand("papyrus");
const pilobolus = getSiteBrand("pilobol-us");
assert.notEqual(anthus.themeTokens.paper, papyrus.themeTokens.paper);
assert.notEqual(anthus.themeTokens.paper, pilobolus.themeTokens.paper);
assert.notEqual(anthus.themeTokens.moss, pilobolus.themeTokens.moss);

// --- theme CSS ------------------------------------------------------------

const themeCss = fs.readFileSync(
  path.join(process.cwd(), "publications/anth_us/theme.css"),
  "utf8",
);
assert.match(themeCss, /data-theme-pack="anth-us"/);
assert.match(themeCss, /--theme-paper:\s*#f1f9fe/);
assert.match(themeCss, /--theme-ink:\s*#333333/);
assert.match(themeCss, /--theme-moss:\s*#dc5497/);
assert.match(themeCss, /--theme-ochre:\s*#ff57b4/);
assert.match(themeCss, /--theme-card:\s*#ffffff/);
assert.match(themeCss, /--theme-line:\s*#cccccc/);
assert.match(themeCss, /--theme-quote:\s*#9b165d/);
assert.match(themeCss, /--theme-tip:\s*#0389d7/);
assert.match(themeCss, /--theme-caution:\s*#e95800/);
assert.match(themeCss, /--theme-stage:\s*#fedded/);
assert.match(themeCss, /--primary:\s*var\(--theme-moss\)/);
assert.match(themeCss, /--accent:\s*var\(--theme-ochre\)/);
assert.match(themeCss, /--destructive:\s*var\(--theme-caution\)/);
assert.match(themeCss, /color-scheme:\s*light/);
// Colors only: Shadcn owns typography, and the pack must not ship a face.
assert.doesNotMatch(themeCss, /(?:^|[^-])font-family\s*:/);
assert.doesNotMatch(themeCss, /@font-face/);
assert.doesNotMatch(themeCss, /Jersey 25|Montserrat|Geist Mono/i);

// The pack is imported through the dev-only theme aggregator, not inlined: no
// Anthus hexes in framework CSS.
const sharedGlobals = fs.readFileSync(
  path.join(process.cwd(), "app/globals.css"),
  "utf8",
);
const devThemes = fs.readFileSync(path.join(process.cwd(), "app/dev-themes.css"), "utf8");
assert.match(devThemes, /@import "\.\.\/publications\/anth_us\/theme\.css";/);
assert.doesNotMatch(sharedGlobals, /publications\//);
assert.doesNotMatch(sharedGlobals, /#f1f9fe|#dc5497|#ff57b4|#fedded|#9b165d/i);

// --- stack axes stay independent -----------------------------------------

const anthusStack = getSiteStack(anthus);
assert.equal(anthusStack.ops.themePack, "anth-us");
assert.equal(anthusStack.ops.chrome, "app");
assert.equal(anthusStack.publication.renderer.kind, "markus");
assert.equal(anthusStack.hosting.kind, "amplify-ssr");
assert.equal(anthusStack.ops.chrome, getSiteStack(papyrus).ops.chrome);

console.log("anth-us brand tests passed");

function registerTypeScriptRequire() {
  if (require.extensions[".ts"]) return;
  require.extensions[".ts"] = (module, filename) => {
    const source = fs.readFileSync(filename, "utf8");
    const output = ts.transpileModule(source, {
      compilerOptions: {
        esModuleInterop: true,
        module: ts.ModuleKind.CommonJS,
        moduleResolution: ts.ModuleResolutionKind.Node10,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: filename,
    });
    module._compile(output.outputText, filename);
  };
}
