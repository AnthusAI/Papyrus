import path from "node:path";

/**
 * Wrap a publication repo's Next config for Papyrus (SPIKE, PPY-82be6c).
 * - transpile the package (it ships TypeScript source),
 * - alias `papyrus-site` -> ./papyrus.config.ts and
 *   `papyrus-amplify-outputs` -> ./amplify_outputs.json (both webpack and turbopack),
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

export function withPapyrus(nextConfig = {}, options = {}) {
  const root = options.root ?? process.cwd();
  const aliases = {
    "papyrus-site": path.join(root, "papyrus.config.ts"),
    "papyrus-amplify-outputs": path.join(root, "amplify_outputs.json"),
  };
  return {
    distDir: process.env.NEXT_DIST_DIR || ".next",
    ...nextConfig,
    transpilePackages: [...new Set([...(nextConfig.transpilePackages ?? []), "@anthusai/papyrus"])],
    serverExternalPackages: [...new Set([...(nextConfig.serverExternalPackages ?? []), ...SERVER_EXTERNAL])],
    images: nextConfig.images ?? { remotePatterns: [{ protocol: "https", hostname: "**" }] },
    experimental: { devtoolSegmentExplorer: false, ...nextConfig.experimental },
    turbopack: {
      ...nextConfig.turbopack,
      resolveAlias: {
        ...nextConfig.turbopack?.resolveAlias,
        "papyrus-site": "./papyrus.config.ts",
        "papyrus-amplify-outputs": "./amplify_outputs.json",
      },
    },
    webpack(config, context) {
      config.resolve.alias = { ...config.resolve.alias, ...aliases };
      return typeof nextConfig.webpack === "function" ? nextConfig.webpack(config, context) : config;
    },
  };
}
