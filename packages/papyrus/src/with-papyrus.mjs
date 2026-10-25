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
 * - cap static generation at 2 workers x 3 pages (override with PAPYRUS_STATIC_GENERATION_WORKERS / _CONCURRENCY) and retry
 *   failed pages 3 times, so pre-building the reader pages stays under Cognito guest-credential throttles,
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

/**
 * Next sends `stale-while-revalidate` = `expireTime` - `revalidate` (one year by default), so a shared cache may serve a
 * page for a year past its `s-maxage` while it refreshes in the background. Twice the reader's 60 s page lifetime
 * (lib/reader-cache-lifetime.ts) bounds that to 60 s.
 */
export const READER_EXPIRE_TIME_SECONDS = 120;

export const DEFAULT_STATIC_GENERATION_WORKERS = 2;
export const DEFAULT_STATIC_GENERATION_CONCURRENCY = 3;
export const DEFAULT_STATIC_GENERATION_RETRY_COUNT = 3;

function positiveIntegerFromEnvironment(name) {
  const parsed = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

export function staticGenerationSettings() {
  return {
    cpus: positiveIntegerFromEnvironment("PAPYRUS_STATIC_GENERATION_WORKERS") ?? DEFAULT_STATIC_GENERATION_WORKERS,
    staticGenerationMaxConcurrency:
      positiveIntegerFromEnvironment("PAPYRUS_STATIC_GENERATION_CONCURRENCY") ?? DEFAULT_STATIC_GENERATION_CONCURRENCY,
    staticGenerationRetryCount: DEFAULT_STATIC_GENERATION_RETRY_COUNT,
  };
}

export const DEFAULT_TRANSPILE_PACKAGES = ["@anthusai/papyrus", "cyclotron", "chatticus"];

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
    expireTime: READER_EXPIRE_TIME_SECONDS,
    ...nextConfig,
    transpilePackages: mergeTranspilePackages(nextConfig.transpilePackages),
    serverExternalPackages: [...new Set([...(nextConfig.serverExternalPackages ?? []), ...SERVER_EXTERNAL])],
    outputFileTracingIncludes: mergeOutputFileTracingIncludes(nextConfig.outputFileTracingIncludes),
    images: nextConfig.images ?? { remotePatterns: [{ protocol: "https", hostname: "**" }] },
    experimental: { devtoolSegmentExplorer: false, ...staticGenerationSettings(), ...nextConfig.experimental },
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
