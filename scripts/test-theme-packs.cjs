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
assert.match(pilobol.themeTokens.paper, /^#/);
assert.match(pilobol.themeTokens.moss, /^#/);
assert.match(pilobol.themeTokens.ochre, /^#/);

const papyrus = getSiteBrand("papyrus");
assert.equal(papyrus.themePack, "papyrus");
assert.equal(papyrus.renderer.kind, "pretext");
assert.equal(papyrus.hosting.kind, "amplify-ssr");
assert.equal(papyrus.opsChrome, "app");
assert.notEqual(papyrus.renderer.kind, pilobol.renderer.kind);
assert.notEqual(papyrus.hosting.kind, pilobol.hosting.kind);

const shellSource = fs.readFileSync(path.join(process.cwd(), "components/newsroom-app-shell.tsx"), "utf8");
assert.doesNotMatch(shellSource, /pilobol|threat-intelligence|papyrus/i);

const themeCss = fs.readFileSync(path.join(process.cwd(), "publications/pilobol_us/theme.css"), "utf8");
assert.match(themeCss, /--theme-paper/);
assert.match(themeCss, /--theme-moss/);
assert.match(themeCss, /--theme-ochre/);

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
