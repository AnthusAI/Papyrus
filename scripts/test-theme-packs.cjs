#!/usr/bin/env node

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

registerTypeScriptRequire();

const {
  getSiteBrand,
  normalizeSiteBrandId,
  resolveSiteBrandId,
} = require("../lib/site-brand.ts");
const { PILOBOL_US_THEME_PACK_TOKENS } = require("../lib/site-stack.ts");

assert.equal(resolveSiteBrandId("pilobol-us"), "pilobol-us");
assert.equal(resolveSiteBrandId("pilobolus"), "pilobol-us");
assert.equal(resolveSiteBrandId("pilobol.us"), "pilobol-us");
assert.equal(normalizeSiteBrandId("unknown"), null);
assert.equal(resolveSiteBrandId("not-a-brand"), "papyrus");

const pilobol = getSiteBrand("pilobol-us");
assert.equal(pilobol.themePack, "pilobol-us");
assert.equal(pilobol.opsChrome, "app");
assert.equal(pilobol.renderer.kind, "markus");
assert.equal(pilobol.hosting.kind, "amplify-static");
assert.deepEqual(pilobol.themeTokens, PILOBOL_US_THEME_PACK_TOKENS);
assert.equal(pilobol.themeTokens.paper, "#f1ead9");
assert.equal(pilobol.themeTokens.moss, "#3f5d43");
assert.equal(pilobol.themeTokens.ochre, "#a35a2a");
assert.equal(pilobol.themeTokens.ink, "#211d17");
assert.equal(pilobol.themeTokens.card, "#fbf6ea");
assert.equal(pilobol.themeTokens.line, "#d7cbb2");
assert.equal(pilobol.themeTokens.muted, "#6b6153");
assert.equal(pilobol.themeTokens.quote, "#4a3548");
assert.equal(pilobol.themeTokens.tip, "#4f6b3a");
assert.equal(pilobol.themeTokens.caution, "#8a3324");
assert.equal(pilobol.themeTokens.stage, "#ddd4bf");
assert.equal(pilobol.themeTokens.dark.paper, "#14170f");
assert.equal(pilobol.themeTokens.dark.moss, "#b7d18a");
assert.equal(pilobol.themeTokens.dark.ochre, "#d0895a");
assert.equal(pilobol.themeTokens.dark.ink, "#dfded0");
assert.equal(pilobol.themeTokens.dark.caution, "#d17e6e");

const papyrus = getSiteBrand("papyrus");
assert.equal(papyrus.themePack, "papyrus");
assert.equal(papyrus.renderer.kind, "pretext");
assert.equal(papyrus.hosting.kind, "amplify-ssr");
assert.equal(papyrus.opsChrome, "app");
assert.notEqual(papyrus.renderer.kind, pilobol.renderer.kind);
assert.notEqual(papyrus.hosting.kind, pilobol.hosting.kind);
assert.notEqual(papyrus.themeTokens.paper, pilobol.themeTokens.paper);
assert.notEqual(papyrus.themeTokens.moss, pilobol.themeTokens.moss);

const threatIntel = getSiteBrand("threat-intelligence");
assert.equal(threatIntel.themePack, "threat-intelligence");
assert.equal(threatIntel.opsChrome, "app");
assert.equal(threatIntel.renderer.kind, "pretext");
assert.notEqual(threatIntel.themeTokens.paper, pilobol.themeTokens.paper);
assert.notEqual(threatIntel.themeTokens.ochre, pilobol.themeTokens.ochre);

const shellSource = fs.readFileSync(path.join(process.cwd(), "components/newsroom-app-shell.tsx"), "utf8");
assert.doesNotMatch(shellSource, /pilobol|threat-intelligence|papyrus/i);
assert.doesNotMatch(shellSource, /#f1ead9|#3f5d43|#a35a2a|#211d17/i);

const sharedGlobals = fs.readFileSync(path.join(process.cwd(), "app/globals.css"), "utf8");
assert.doesNotMatch(sharedGlobals, /#f1ead9|#3f5d43|#a35a2a|#211d17|#fbf6ea|#d7cbb2|#4a3548|#8a3324/);

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
