module.exports = {
  branches: ["main", { name: "develop", prerelease: "next", channel: "next" }],
  plugins: [
    ["@semantic-release/commit-analyzer", { preset: "conventionalcommits" }],
    ["@semantic-release/release-notes-generator", { preset: "conventionalcommits" }],
    ["@semantic-release/exec", {
      prepareCmd: "node packages/stage.mjs --version ${nextRelease.version} && node packages/verify-packages.mjs ${nextRelease.version}",
      publishCmd: "npm publish ./dist-packages/anthusai-papyrus-${nextRelease.version}.tgz --access public --provenance --tag ${nextRelease.channel || 'latest'}",
      successCmd: "echo \"published=true\" >> \"$GITHUB_OUTPUT\" && echo \"version=${nextRelease.version}\" >> \"$GITHUB_OUTPUT\""
    }],
    "@semantic-release/github"
  ]
};
