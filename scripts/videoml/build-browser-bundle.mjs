#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "../..");
const babulusRoot = process.env.BABULUS_ROOT || path.join(process.env.HOME || "", "Projects/Babulus");
const require = createRequire(import.meta.url);

function resolveEsbuild() {
  const candidates = [
    path.join(projectRoot, "node_modules/esbuild"),
    path.join(babulusRoot, "node_modules/esbuild"),
  ];
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch {
      continue;
    }
  }
  throw new Error("esbuild not found. Run npm install in Papyrus or set BABULUS_ROOT to a Babulus checkout with dependencies.");
}

const globalsPlugin = {
  name: "globals",
  setup(build) {
    build.onResolve({ filter: /^react$/ }, () => ({ path: "react", namespace: "globals" }));
    build.onResolve({ filter: /^react-dom$/ }, () => ({ path: "react-dom", namespace: "globals" }));
    build.onResolve({ filter: /^react-dom\/client$/ }, () => ({ path: "react-dom/client", namespace: "globals" }));
    build.onResolve({ filter: /^react\/jsx-runtime$/ }, () => ({ path: "react/jsx-runtime", namespace: "globals" }));
    build.onResolve({ filter: /^react\/jsx-dev-runtime$/ }, () => ({ path: "react/jsx-dev-runtime", namespace: "globals" }));

    const jsxRuntimeShim = `
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

    build.onLoad({ filter: /.*/, namespace: "globals" }, (args) => {
      if (args.path === "react") {
        return { contents: "module.exports = window.React", loader: "js" };
      }
      if (args.path === "react-dom" || args.path === "react-dom/client") {
        return { contents: "module.exports = window.ReactDOM", loader: "js" };
      }
      if (args.path === "react/jsx-runtime" || args.path === "react/jsx-dev-runtime") {
        return { contents: jsxRuntimeShim, loader: "js" };
      }
      return null;
    });

    build.onResolve({ filter: /^babulus-browser-bundle$/ }, () => ({
      path: path.join(babulusRoot, "scripts/browser-bundle.tsx"),
    }));

    build.onResolve({ filter: /^babulus-renderer\// }, (args) => {
      const subpath = args.path.replace(/^babulus-renderer\//, "");
      const base = path.join(babulusRoot, "packages/renderer/src", subpath);
      if (fs.existsSync(`${base}.tsx`)) return { path: `${base}.tsx` };
      if (fs.existsSync(`${base}.ts`)) return { path: `${base}.ts` };
      return { path: base };
    });
  },
};

async function bundle() {
  if (!fs.existsSync(path.join(babulusRoot, "scripts/browser-bundle.tsx"))) {
    throw new Error(`Babulus checkout not found at ${babulusRoot}. Set BABULUS_ROOT.`);
  }

  const esbuild = resolveEsbuild();
  const outDir = path.join(projectRoot, "public/videoml");
  fs.mkdirSync(outDir, { recursive: true });
  const outfile = path.join(outDir, "ti-browser-bundle.js");

  await esbuild.build({
    entryPoints: [path.join(projectRoot, "publications/threat_intelligence/videoml/browser-bundle.tsx")],
    bundle: true,
    format: "iife",
    outfile,
    platform: "browser",
    jsx: "automatic",
    // Papyrus uses React 19 locally; Babulus Playwright pages load React 18 UMD globals.
    // The globals plugin shims react/jsx-runtime to React.createElement on window.React.
    absWorkingDir: projectRoot,
    plugins: [globalsPlugin],
    loader: {
      ".tsx": "tsx",
      ".ts": "ts",
    },
    sourcemap: true,
    logLevel: "info",
  });

  console.error(`✓ TI VideoML browser bundle: ${outfile}`);
}

bundle().catch((error) => {
  console.error(error);
  process.exit(1);
});
