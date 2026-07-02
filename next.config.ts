import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  experimental: {
    // Work around unstable Next dev segment-explorer module wiring in webpack dev mode.
    devtoolSegmentExplorer: false,
  },
  serverExternalPackages: [
    "aws-amplify",
    "@aws-amplify/adapter-nextjs",
    "@aws-amplify/core",
    "@aws-amplify/api",
    "@aws-amplify/api-graphql",
    "@aws-amplify/auth",
    "@aws-amplify/storage",
    "@aws-amplify/data-schema",
  ],
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "**",
      },
    ],
  },
};

export default nextConfig;
