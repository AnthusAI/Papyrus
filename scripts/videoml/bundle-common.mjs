import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const scriptsDirectory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

const OPTIONAL_DYNAMIC_IMPORTS_OF_VIDEOML = ["p5", "lottie-web", "animejs"];

const REACT_GLOBALS_JSX_RUNTIME = `
var React = window.React;
function jsx(type, config, maybeKey) {
  var props = config || {};
  var key = maybeKey !== undefined ? maybeKey : props.key;
  if (key !== undefined) {
    props = Object.assign({}, props, { key: key });
  }
  return React.createElement(type, props);
}
exports.Fragment = React.Fragment;
exports.jsx = jsx;
exports.jsxs = jsx;
`;

const reactGlobalsPlugin = {
  name: "react-globals",
  setup(build) {
    const globals = {
      react: "module.exports = window.React",
      "react-dom": "module.exports = window.ReactDOM",
      "react-dom/client": "module.exports = window.ReactDOM",
      "react/jsx-runtime": REACT_GLOBALS_JSX_RUNTIME,
      "react/jsx-dev-runtime": REACT_GLOBALS_JSX_RUNTIME,
    };
    build.onResolve({ filter: /^react(-dom)?(\/.*)?$/ }, (args) =>
      args.path in globals ? { path: args.path, namespace: "react-globals" } : undefined,
    );
    build.onLoad({ filter: /.*/, namespace: "react-globals" }, (args) => ({
      contents: globals[args.path],
      loader: "js",
    }));
  },
};

export function resolveSelectedBrandId(site, env) {
  const requested = (env.PAPYRUS_SITE_BRAND ?? "").trim();
  return requested || site.defaultBrand || "papyrus";
}

/**
 * Loads the publication's `papyrus.config.ts` from the project root and returns the
 * selected brand's `video` slot. Fails with a message naming the missing piece.
 */
export async function loadBrandVideoSlot(projectRoot, env = process.env) {
  const configPath = path.join(projectRoot, "papyrus.config.ts");
  if (!fs.existsSync(configPath)) {
    throw new Error(`No papyrus.config.ts in ${projectRoot}. Run the VideoML bundle builder from the publication root.`);
  }
  const { tsImport } = await import("tsx/esm/api");
  // Inside a Papyrus checkout, brand components import lib/site-brand, which imports this
  // config: load site-brand first so the cycle resolves in the same order as in the app.
  const checkoutSiteBrand = path.join(projectRoot, "lib/site-brand.ts");
  if (fs.existsSync(checkoutSiteBrand)) await tsImport(pathToFileURL(checkoutSiteBrand).href, import.meta.url);
  const loaded = await tsImport(pathToFileURL(configPath).href, import.meta.url);
  const exported = loaded.default ?? loaded;
  const site = exported.brands === undefined && exported.default ? exported.default : exported;
  const brandId = resolveSelectedBrandId(site, env);
  const brand = (site.brands ?? []).find((candidate) => candidate.id === brandId);
  if (!brand) {
    const registered = (site.brands ?? []).map((candidate) => candidate.id).join(", ") || "none";
    throw new Error(`Brand '${brandId}' is not registered in papyrus.config.ts (registered: ${registered}).`);
  }
  if (!brand.video || typeof brand.video.bundleEntry !== "string" || !brand.video.bundleEntry) {
    throw new Error(
      `Brand '${brandId}' has no brand.video.bundleEntry in papyrus.config.ts. ` +
        "Set brand.video = { bundleEntry: \"<path to a TSX module that registers the brand's VideoML scene components>\" }.",
    );
  }
  const bundleEntry = path.resolve(projectRoot, brand.video.bundleEntry);
  if (!fs.existsSync(bundleEntry)) {
    throw new Error(`brand.video.bundleEntry for '${brandId}' does not exist: ${bundleEntry}`);
  }
  return { brandId, bundleEntry, video: brand.video };
}

function resolveEsbuild(projectRoot) {
  for (const base of [projectRoot, scriptsDirectory]) {
    try {
      return require(require.resolve("esbuild", { paths: [base] }));
    } catch {
      continue;
    }
  }
  throw new Error("esbuild not found. Install it in the publication (npm install --save-dev esbuild).");
}

/**
 * Bundles [standard entry, optional extra entries, brand entry] into one IIFE.
 * React comes from `window.React` / `window.ReactDOM` (the render shell loads React 18 UMD).
 */
export async function bundleVideoEntries({ projectRoot, entries, outfile }) {
  const esbuild = resolveEsbuild(projectRoot);
  fs.mkdirSync(path.dirname(outfile), { recursive: true });
  const importLines = entries.map((entry) => `import ${JSON.stringify(entry)};`).join("\n");
  await esbuild.build({
    stdin: { contents: importLines, resolveDir: projectRoot, sourcefile: "papyrus-videoml-entry.ts", loader: "ts" },
    bundle: true,
    format: "iife",
    platform: "browser",
    jsx: "automatic",
    outfile,
    absWorkingDir: projectRoot,
    nodePaths: [path.join(projectRoot, "node_modules")],
    external: OPTIONAL_DYNAMIC_IMPORTS_OF_VIDEOML,
    plugins: [reactGlobalsPlugin],
    loader: { ".tsx": "tsx", ".ts": "ts" },
    define: { "process.env.NODE_ENV": '"production"' },
    sourcemap: true,
    logLevel: "warning",
  });
  const size = fs.statSync(outfile).size;
  if (size === 0) throw new Error(`VideoML bundle is empty: ${outfile}`);
  return { outfile, size };
}

export const standardEntryPath = path.join(scriptsDirectory, "standard-entry.tsx");
export const previewEntryPath = path.join(scriptsDirectory, "preview/preview-entry.tsx");
export const previewHtmlTemplatePath = path.join(scriptsDirectory, "preview.html");
