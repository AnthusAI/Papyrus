#!/usr/bin/env node
/**
 * Stage and `npm pack` @anthusai/papyrus from this checkout (SPIKE, PPY-82be6c).
 *
 * The Papyrus repo root stays an ordinary Next app; the package is assembled
 * by copying the app code into a staging dir. Only the rewrites that a
 * consumer's node_modules layout forces are applied (listed in `rewrites`):
 *
 *  1. `@/x` imports (consumer tsconfig owns `@/`) -> relative imports.
 *  2. Tailwind `@source "../node_modules/<pkg>/..."` -> `../../../<pkg>/...`
 *     (npm hoists dependencies to the consumer's node_modules).
 *  3. Route modules are scanned into `routes.manifest.json` for `papyrus-app sync`.
 *
 * Usage: node packages/papyrus/scripts/stage.mjs [--version 1.2.3] [--out dir]
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const pkgDir = path.resolve(here, "..");
const repo = path.resolve(pkgDir, "../..");
const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
};
const version = opt("version", "0.0.0-spike.0");
const outRoot = path.resolve(opt("out", path.join(repo, "dist-packages")));
const stage = path.join(outRoot, "stage-papyrus");

const COPY_ROOTS = ["app", "components", "lib", "renderers", "amplify", "middleware.ts"];
const SKIP = [/^app\/dev-themes\.css$/, /^amplify\/backend\.ts$/, /\.test\.(mjs|ts)$/, /^amplify\/fixtures\//, /^amplify\/seed\//, /\.DS_Store$/, /__pycache__/, /\.pyc$/];
const CODE_EXT = [".ts", ".tsx", ".mts", ".js", ".mjs", ".cjs", ".json", ".css"];

fs.rmSync(stage, { recursive: true, force: true });
fs.mkdirSync(stage, { recursive: true });

const copied = new Set();
function copyFile(rel) {
  if (copied.has(rel) || SKIP.some((re) => re.test(rel))) return;
  copied.add(rel);
  const dest = path.join(stage, rel);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(path.join(repo, rel), dest);
}
function walk(rel) {
  const abs = path.join(repo, rel);
  const st = fs.statSync(abs);
  if (st.isDirectory()) {
    for (const entry of fs.readdirSync(abs)) walk(path.join(rel, entry));
  } else copyFile(rel);
}
for (const root of COPY_ROOTS) walk(root);
for (const entry of fs.readdirSync(path.join(repo, "scripts/videoml"), { recursive: true, withFileTypes: true })) {
  if (entry.isFile()) copyFile(path.relative(repo, path.join(entry.parentPath, entry.name)));
}

// Pull in files outside the copied roots that copied code imports (transitively),
// e.g. publications/<id>/brand.ts and theme.css.
const specRe = /(?:from\s+|import\s+|require\(\s*|@import\s+)["']([^"']+)["']/g;
function resolveRel(fromRel, spec) {
  const base = path.resolve(path.join(repo, path.dirname(fromRel)), spec);
  const candidates = [base, ...CODE_EXT.map((e) => base + e), ...CODE_EXT.map((e) => path.join(base, "index" + e))];
  return candidates.find((c) => fs.existsSync(c) && fs.statSync(c).isFile());
}
const queue = [...copied];
const external = new Set();
while (queue.length) {
  const rel = queue.pop();
  if (!CODE_EXT.includes(path.extname(rel)) || rel.endsWith(".json")) continue;
  const text = fs.readFileSync(path.join(repo, rel), "utf8");
  for (const m of text.matchAll(specRe)) {
    const spec = m[1];
    if (!spec.startsWith(".")) continue;
    const abs = resolveRel(rel, spec);
    if (!abs) continue;
    const target = path.relative(repo, abs);
    if (target.startsWith("..")) continue;
    if (!copied.has(target)) {
      external.add(target);
      copyFile(target);
      queue.push(target);
    }
  }
}

const pulledInPublications = [...copied].filter((rel) => rel.startsWith("publications/")).sort();
if (pulledInPublications.length > 0) {
  throw new Error(
    `The package must contain no publication code, but staging pulled in: ${pulledInPublications.join(", ")}`,
  );
}

// ---- rewrites -------------------------------------------------------------
const rewrites = { atAlias: 0, tailwindSource: 0 };
function rewriteFile(rel) {
  const file = path.join(stage, rel);
  let text = fs.readFileSync(file, "utf8");
  const original = text;
  if (/\.(ts|tsx|mts)$/.test(rel)) {
    text = text.replace(/(from\s+|import\s*\(\s*|import\s+)(["'])@\/([^"']+)\2/g, (_m, pre, q, spec) => {
      let relPath = path.relative(path.dirname(rel), spec).split(path.sep).join("/");
      if (!relPath.startsWith(".")) relPath = "./" + relPath;
      rewrites.atAlias++;
      return `${pre}${q}${relPath}${q}`;
    });
  }
  if (rel === "app/tailwind.css") {
    text = text.replace(/@source "\.\.\/node_modules\//g, () => {
      rewrites.tailwindSource++;
      return '@source "../../../';
    });
  }
  if (text !== original) fs.writeFileSync(file, text);
}
for (const rel of copied) rewriteFile(rel);

// ---- compiled JS for what `ampx` (Node + tsx) loads from node_modules ---------
// Node refuses type stripping under node_modules (ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING)
// and ampx's tsx loader does not rescue it on current Node, so the backend
// definition ships as ESM JS next to its TS source. Handlers (esbuild-bundled
// by Amplify) stay TS-only.
import { createRequire } from "node:module";
const requireTs = createRequire(path.join(process.env.PAPYRUS_TS_RESOLVE_FROM ?? repo, "noop.js"));
const ts = requireTs("typescript");
const HANDLER_SIDE = /^amplify\/(functions\/[^/]+\/handler\.ts|functions\/shared\/(?!python-bundle)|seed\/|.*\.test\.)/;
const compileList = [...copied].filter((r) => /^amplify\/.*\.ts$/.test(r) && !HANDLER_SIDE.test(r));
compileList.push("lib/define-site.ts");
const compiled = new Set(compileList.map((r) => r.replace(/\.ts$/, ".js")));
const writeCompiled = (rel) => {
  const file = path.join(stage, rel);
  let out = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    fileName: rel,
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: false },
  }).outputText;
  out = out.replace(/((?:from\s+|import\s*\(\s*)["'])(\.{1,2}\/[^"']+)(["'])/g, (m, pre, spec, post) => {
    const base = path.posix.join(path.posix.dirname(rel), spec);
    if (compiled.has(base + ".js")) return `${pre}${spec}.js${post}`;
    if (compiled.has(base + "/index.js")) return `${pre}${spec}/index.js${post}`;
    if (compiled.has(base)) return m;
    throw new Error(`${rel}: relative import "${spec}" does not resolve to a compiled file`);
  });
  fs.writeFileSync(path.join(stage, rel.replace(/\.ts$/, ".js")), out);
};
for (const rel of compileList) writeCompiled(rel);
fs.mkdirSync(path.join(stage, "src"), { recursive: true });
fs.writeFileSync(
  path.join(stage, "src/backend.js"),
  'export { defineSiteBackend } from "../amplify/site-backend.js";\n',
);

// ---- infra: app-shell CDK constructs (subpath export `@anthusai/papyrus/infra`) ----
{
  const src = path.join(repo, "infra/amplify-app-shell/lib");
  fs.mkdirSync(path.join(stage, "infra"), { recursive: true });
  for (const name of fs.readdirSync(src).filter((n) => n.endsWith(".ts"))) {
    const source = fs.readFileSync(path.join(src, name), "utf8");
    fs.writeFileSync(path.join(stage, "infra", name), source);
    const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
      .replace(/(from\s+["'])(\.\/[^"']+)(["'])/g, "$1$2.js$3");
    fs.writeFileSync(path.join(stage, "infra", name.replace(/\.ts$/, ".js")), compiled);
  }
  fs.writeFileSync(path.join(stage, "infra/index.js"), `// aws-cdk-lib and constructs are OPTIONAL peers of @anthusai/papyrus: only a publication's infra/ package installs them.
try {
  await import("aws-cdk-lib");
  await import("constructs");
} catch (error) {
  throw new Error(
    "@anthusai/papyrus/infra needs aws-cdk-lib and constructs, which are optional peer dependencies. " +
      "Install them in the package that imports this entry (your infra/ folder): npm install aws-cdk-lib constructs. " +
      "(" + (error && error.code) + ")",
  );
}
export const { AmplifyAppShellStack } = await import("./amplify-app-shell.js");
export const { GithubOidcProviderStack } = await import("./github-oidc-provider.js");
export { parseSiteConfig } from "./site-config.js";
export { cmsProductionBuildSpec, cmsStagingBuildSpec, readerBuildSpec, buildSpecFor } from "./build-specs.js";
`);
}

// ---- route manifest -------------------------------------------------------
const ROUTE_FILE = /^app\/(?:.*\/)?(page|layout|route|loading|error|not-found|template|default)\.(tsx|ts)$/;
const SEGMENT_CONFIG = ["dynamic", "revalidate", "runtime", "maxDuration", "fetchCache", "preferredRegion", "dynamicParams"];
const routes = [];
for (const rel of [...copied].filter((r) => ROUTE_FILE.test(r)).sort()) {
  const text = fs.readFileSync(path.join(stage, rel), "utf8");
  const exportsFound = new Set();
  const config = {};
  for (const m of text.matchAll(/export\s+(?:async\s+)?(?:function|const|let)\s+([A-Za-z0-9_]+)/g)) exportsFound.add(m[1]);
  for (const m of text.matchAll(/export\s*\{([^}]+)\}/g)) {
    for (const part of m[1].split(",")) {
      const name = part.trim().split(/\s+as\s+/).pop();
      if (name && !part.includes(" type ") && !part.trim().startsWith("type ")) exportsFound.add(name);
    }
  }
  for (const name of SEGMENT_CONFIG) {
    const m = text.match(new RegExp(`export\\s+const\\s+${name}\\s*=\\s*([^;\\n]+)`));
    if (m) config[name] = m[1].trim();
  }
  routes.push({
    file: rel,
    hasDefault: /export\s+default/.test(text),
    exports: [...exportsFound].filter((n) => !SEGMENT_CONFIG.includes(n) && n !== "default").sort(),
    config,
  });
}
const middlewareText = fs.readFileSync(path.join(stage, "middleware.ts"), "utf8");
const matcher = middlewareText.match(/matcher:\s*(\[[^\]]*\])/);
const manifest = {
  version,
  routes,
  middleware: { file: "middleware.ts", matcher: matcher ? matcher[1] : null },
};
fs.writeFileSync(path.join(stage, "routes.manifest.json"), JSON.stringify(manifest, null, 2) + "\n");

// ---- package.json ---------------------------------------------------------
const root = JSON.parse(fs.readFileSync(path.join(repo, "package.json"), "utf8"));
const template = JSON.parse(fs.readFileSync(path.join(pkgDir, "package.template.json"), "utf8"));
const peerNames = Object.keys(template.peerDependencies ?? {});
const dependencies = { ...root.dependencies };
for (const name of peerNames) delete dependencies[name];
for (const name of ["aws-cdk-lib", "constructs"]) delete dependencies[name]; // optional peers now
// @aws-amplify/backend{,-cli,/seed} are optional peers: the publication lists them (dev) itself.
delete dependencies["@aws-amplify/seed"];
// Exact subpath exports for every route module: webpack takes only the first
// target of an exports array, so `./app/*` -> [".tsx", ".ts"] fails for `.ts` routes.
const exportsMap = { ...template.exports };
for (const rel of [...copied].filter((r) => /^(lib|components|renderers)\/.*\.(ts|tsx)$/.test(r))) exportsMap[`./${rel.replace(/\.(tsx|ts)$/, "")}`] = `./${rel}`;
for (const route of routes) exportsMap[`./${route.file.replace(/\.(tsx|ts)$/, "")}`] = `./${route.file}`;
const pkg = { ...template, version, dependencies, exports: exportsMap };
fs.writeFileSync(path.join(stage, "package.json"), JSON.stringify(pkg, null, 2) + "\n");

// ---- package-owned files --------------------------------------------------
fs.mkdirSync(path.join(stage, "bin"), { recursive: true });
fs.mkdirSync(path.join(stage, "src"), { recursive: true });
for (const f of ["bin/papyrus-app.mjs", "bin/papyrus-infra.mjs", "src/with-papyrus.mjs", "src/with-papyrus.d.mts", "src/sync.mjs", "src/backend.ts"]) {
  fs.copyFileSync(path.join(pkgDir, f), path.join(stage, f));
}
fs.copyFileSync(path.join(repo, "LICENSE"), path.join(stage, "LICENSE"));

// ---- pack ---------------------------------------------------------------
fs.mkdirSync(outRoot, { recursive: true });
const out = execFileSync("npm", ["pack", "--pack-destination", outRoot, "--json"], { cwd: stage, encoding: "utf8" });
const info = JSON.parse(out)[0];
console.log(JSON.stringify({
  tarball: path.join(outRoot, info.filename),
  files: info.entryCount,
  packedBytes: info.size,
  unpackedBytes: info.unpackedSize,
  rewrites,
  externalFilesPulledIn: [...external].sort(),
  routes: routes.length,
}, null, 2));
