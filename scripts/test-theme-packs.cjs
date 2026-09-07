#!/usr/bin/env node

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

registerTypeScriptRequire();

const {
  getSiteBrand,
  normalizeSiteBrandId,
  resolveRuntimeSiteBrandId,
  resolveSiteBrandId,
} = require("../lib/site-brand.ts");
const { isDemoAmplifyOutputs } = require("../lib/demo-amplify-outputs.ts");
const { getNewsroomDemoProfile } = require("../lib/newsroom-demo-profile.ts");
const { getSiteStack, PILOBOL_US_THEME_PACK_TOKENS } = require("../lib/site-stack.ts");

assert.equal(resolveSiteBrandId("pilobol-us"), "pilobol-us");
assert.equal(resolveSiteBrandId("pilobolus"), "pilobol-us");
assert.equal(resolveSiteBrandId("pilobol.us"), "pilobol-us");
assert.equal(normalizeSiteBrandId("pilobol"), null);
assert.equal(resolveSiteBrandId("pilobol"), "papyrus");
assert.equal(normalizeSiteBrandId("unknown"), null);
assert.equal(resolveSiteBrandId("not-a-brand"), "papyrus");

assert.equal(resolveRuntimeSiteBrandId("pilobol-us"), "pilobol-us");
assert.equal(resolveRuntimeSiteBrandId(null), resolveSiteBrandId());

const pilobolusDemo = getNewsroomDemoProfile("pilobol-us");
assert.match(pilobolusDemo.canonicalCorpusName, /Pilobolus/);
assert.equal(pilobolusDemo.classifierId, "pilobolus-demo-classifier");

const middlewareSource = fs.readFileSync(path.join(process.cwd(), "middleware.ts"), "utf8");
assert.match(middlewareSource, /papyrus-site-brand-override/);
assert.match(middlewareSource, /normalizeSiteBrandId/);

assert.equal(isDemoAmplifyOutputs(), false);

const pilobolus = getSiteBrand("pilobol-us");
assert.equal(pilobolus.appTitle, "Pilobolus");
assert.match(pilobolus.appDescription, /Pilobolus/);
assert.match(pilobolus.appDescription, /Pilobol\.us/);
assert.equal(pilobolus.themePack, "pilobol-us");
assert.equal(pilobolus.opsChrome, "app");
assert.equal(pilobolus.renderer.kind, "markus");
assert.equal(pilobolus.hosting.kind, "amplify-static");
assert.deepEqual(pilobolus.themeTokens, PILOBOL_US_THEME_PACK_TOKENS);
assert.equal(pilobolus.themeTokens.paper, "#f1ead9");
assert.equal(pilobolus.themeTokens.moss, "#3f5d43");
assert.equal(pilobolus.themeTokens.ochre, "#a35a2a");
assert.equal(pilobolus.themeTokens.ink, "#211d17");
assert.equal(pilobolus.themeTokens.card, "#fbf6ea");
assert.equal(pilobolus.themeTokens.line, "#d7cbb2");
assert.equal(pilobolus.themeTokens.muted, "#6b6153");
assert.equal(pilobolus.themeTokens.quote, "#4a3548");
assert.equal(pilobolus.themeTokens.tip, "#4f6b3a");
assert.equal(pilobolus.themeTokens.caution, "#8a3324");
assert.equal(pilobolus.themeTokens.stage, "#ddd4bf");
assert.equal(pilobolus.themeTokens.dark.paper, "#14170f");
assert.equal(pilobolus.themeTokens.dark.moss, "#b7d18a");
assert.equal(pilobolus.themeTokens.dark.ochre, "#d0895a");
assert.equal(pilobolus.themeTokens.dark.ink, "#dfded0");
assert.equal(pilobolus.themeTokens.dark.caution, "#d17e6e");

const papyrus = getSiteBrand("papyrus");
assert.equal(papyrus.themePack, "papyrus");
assert.equal(papyrus.renderer.kind, "pretext");
assert.equal(papyrus.hosting.kind, "amplify-ssr");
assert.equal(papyrus.opsChrome, "app");
assert.notEqual(papyrus.renderer.kind, pilobolus.renderer.kind);
assert.notEqual(papyrus.hosting.kind, pilobolus.hosting.kind);
assert.notEqual(papyrus.themeTokens.paper, pilobolus.themeTokens.paper);
assert.notEqual(papyrus.themeTokens.moss, pilobolus.themeTokens.moss);

const threatIntel = getSiteBrand("threat-intelligence");
assert.equal(threatIntel.themePack, "threat-intelligence");
assert.equal(threatIntel.opsChrome, "app");
assert.equal(threatIntel.renderer.kind, "pretext");
assert.notEqual(threatIntel.themeTokens.paper, pilobolus.themeTokens.paper);
assert.notEqual(threatIntel.themeTokens.ochre, pilobolus.themeTokens.ochre);

const shellSource = fs.readFileSync(path.join(process.cwd(), "components/newsroom-ops-shell.tsx"), "utf8");
assert.doesNotMatch(shellSource, /pilobol|threat-intelligence|papyrus/i);
assert.doesNotMatch(shellSource, /#f1ead9|#3f5d43|#a35a2a|#211d17/i);

const sharedGlobals = fs.readFileSync(path.join(process.cwd(), "app/globals.css"), "utf8");
assert.doesNotMatch(sharedGlobals, /#f1ead9|#3f5d43|#a35a2a|#211d17|#fbf6ea|#d7cbb2|#4a3548|#8a3324/);

const papyrusStack = getSiteStack(papyrus);
const pilobolusStack = getSiteStack(pilobolus);
assert.equal(papyrusStack.ops.chrome, pilobolusStack.ops.chrome);
assert.equal(papyrusStack.ops.chrome, "app");
assert.notEqual(papyrusStack.publication.renderer.kind, pilobolusStack.publication.renderer.kind);

const mixedPretextOps = getSiteStack({
  ...pilobolus,
  renderer: { kind: "pretext" },
});
assert.equal(mixedPretextOps.ops.themePack, "pilobol-us");
assert.equal(mixedPretextOps.publication.renderer.kind, "pretext");

const mixedMarkusDefault = getSiteStack({
  ...papyrus,
  renderer: { kind: "markus" },
});
assert.equal(mixedMarkusDefault.ops.themePack, "papyrus");
assert.equal(mixedMarkusDefault.publication.renderer.kind, "markus");

const layoutSource = fs.readFileSync(path.join(process.cwd(), "app/layout.tsx"), "utf8");
assert.match(layoutSource, /data-renderer=\{siteStack\.publication\.renderer\.kind\}/);
assert.match(layoutSource, /data-theme-pack=\{siteStack\.ops\.themePack\}/);
assert.match(layoutSource, /data-ops-chrome=\{siteStack\.ops\.chrome\}/);
assert.doesNotMatch(layoutSource, /data-renderer=\{SITE_BRAND\.(themePack|opsChrome)/);

assert.match(shellSource, /data-newsroom-ops-shell/);
assert.match(shellSource, /data-newsroom-ops-bottom-nav/);
assert.match(shellSource, /SheetContent/);

const defaultPackCss = fs.readFileSync(path.join(process.cwd(), "publications/papyrus/theme.css"), "utf8");
assert.match(defaultPackCss, /data-theme-pack="papyrus"/);
assert.match(defaultPackCss, /--theme-paper:\s*var\(--background\)/);

const themeCss = fs.readFileSync(path.join(process.cwd(), "publications/pilobol_us/theme.css"), "utf8");
assert.match(themeCss, /--theme-paper:\s*#f1ead9/);
assert.match(themeCss, /--theme-moss:\s*#3f5d43/);
assert.match(themeCss, /--theme-ochre:\s*#a35a2a/);
assert.match(themeCss, /--theme-ink:\s*#211d17/);
assert.match(themeCss, /--theme-card:\s*#fbf6ea/);
assert.match(themeCss, /--theme-line:\s*#d7cbb2/);
assert.match(themeCss, /--theme-quote:\s*#4a3548/);
assert.match(themeCss, /--theme-tip:\s*#4f6b3a/);
assert.match(themeCss, /--theme-caution:\s*#8a3324/);
assert.match(themeCss, /--theme-stage:\s*#ddd4bf/);
assert.match(themeCss, /prefers-color-scheme:\s*dark/);
assert.match(themeCss, /data-papyrus-theme="dark"/);
assert.match(themeCss, /--theme-moss:\s*#b7d18a/);
assert.match(themeCss, /--primary:\s*var\(--theme-moss\)/);
assert.match(themeCss, /--accent:\s*var\(--theme-ochre\)/);
assert.match(themeCss, /--destructive:\s*var\(--theme-caution\)/);
assert.doesNotMatch(themeCss, /(?:^|[^-])font-family\s*:/);
assert.doesNotMatch(themeCss, /@font-face/);
assert.doesNotMatch(themeCss, /Iowan|Source Sans|IBM Plex|markus-serif|markus-sans/i);

const demoOutputs = JSON.parse(
  fs.readFileSync(path.join(process.cwd(), "amplify/fixtures/demo-amplify-outputs.json"), "utf8"),
);
assert.match(String(demoOutputs.data.url), /nkqutx/);
assert.equal(demoOutputs.auth.user_pool_id, "us-east-1_WD8fuTRVk");
assert.match(String(demoOutputs.auth.user_pool_client_id), /demo|fake|stub|not-a-secret/i);
assert.match(String(demoOutputs.data.api_key), /demo|fake|stub|not-a-secret/i);
assert.doesNotMatch(JSON.stringify(demoOutputs), /64hviw|us-east-1_40Uot7WSv/);

const ensureScript = fs.readFileSync(path.join(process.cwd(), "scripts/ensure-sandbox-amplify-outputs.mjs"), "utf8");
assert.match(ensureScript, /amplify\/fixtures\/demo-amplify-outputs\.json/);
assert.match(ensureScript, /DEMO-ONLY/);
assert.match(ensureScript, /installDemoOutputs/);

console.log("theme pack tests passed");

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
