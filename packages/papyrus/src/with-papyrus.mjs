import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Wrap a publication repo's Next config for Papyrus (SPIKE, PPY-82be6c).
 * - transpile the package and the dependencies that ship TypeScript source (cyclotron),
 * - alias `papyrus-site` -> ./papyrus.config.ts,
 *   `papyrus-amplify-outputs` -> ./amplify_outputs.json and
 *   `papyrus-site-theme` -> ./publication/theme.css when it exists, else the shipped
 *   empty lib/empty-theme.css (both webpack and turbopack),
 * - trace the corpora/ YAML and amplify_outputs.json that the reader reads via fs at runtime,
 * - carry Papyrus's own server-external packages and image settings.
 */
const SERVER_EXTERNAL = [
  "aws-amplify",
  "@aws-amplify/adapter-nextjs",
  "@aws-amplify/core",
  "@aws-amplify/api",
  "@aws-amplify/api-graphql",
  "@aws-amplify/auth",
  "@aws-amplify/storage",
  "@aws-amplify/data-schema",
];

export const DEFAULT_TRANSPILE_PACKAGES = ["@anthusai/papyrus", "cyclotron"];

export function mergeTranspilePackages(existing = []) {
  return [...new Set([...existing, ...DEFAULT_TRANSPILE_PACKAGES])];
}

export const RUNTIME_TRACED_FILES = ["./corpora/**/*", "./amplify_outputs.json"];

export function mergeOutputFileTracingIncludes(existing = {}) {
  const merged = { ...existing };
  const current = merged["/**"] ?? [];
  merged["/**"] = [...new Set([...current, ...RUNTIME_TRACED_FILES])];
  return merged;
}

const EMPTY_THEME = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../lib/empty-theme.css");

export function withPapyrus(nextConfig = {}, options = {}) {
  const root = options.root ?? process.cwd();
  const hasPublicationTheme = fs.existsSync(path.join(root, "publication/theme.css"));
  const toProjectRelative = (absolute) => {
    const relative = path.relative(root, absolute).split(path.sep).join("/");
    return relative.startsWith(".") ? relative : `./${relative}`;
  };
  const aliases = {
    "papyrus-site": path.join(root, "papyrus.config.ts"),
    "papyrus-amplify-outputs": path.join(root, "amplify_outputs.json"),
    "papyrus-site-theme": hasPublicationTheme ? path.join(root, "publication/theme.css") : EMPTY_THEME,
  };
  return {
    distDir: process.env.NEXT_DIST_DIR || ".next",
    ...nextConfig,
    transpilePackages: mergeTranspilePackages(nextConfig.transpilePackages),
    serverExternalPackages: [...new Set([...(nextConfig.serverExternalPackages ?? []), ...SERVER_EXTERNAL])],
    outputFileTracingIncludes: mergeOutputFileTracingIncludes(nextConfig.outputFileTracingIncludes),
    images: nextConfig.images ?? { remotePatterns: [{ protocol: "https", hostname: "**" }] },
    experimental: { devtoolSegmentExplorer: false, ...nextConfig.experimental },
    turbopack: {
      ...nextConfig.turbopack,
      resolveAlias: {
        ...nextConfig.turbopack?.resolveAlias,
        "papyrus-site": "./papyrus.config.ts",
        "papyrus-amplify-outputs": "./amplify_outputs.json",
        "papyrus-site-theme": toProjectRelative(hasPublicationTheme ? path.join(root, "publication/theme.css") : EMPTY_THEME),
      },
    },
    webpack(config, context) {
      config.resolve.alias = { ...config.resolve.alias, ...aliases };
      return typeof nextConfig.webpack === "function" ? nextConfig.webpack(config, context) : config;
    },
  };
}
