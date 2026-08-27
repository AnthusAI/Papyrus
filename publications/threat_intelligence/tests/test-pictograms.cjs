const fs = require("fs");
const path = require("path");

const repoRoot = path.resolve(__dirname, "../../..");

function read(relativePath) {
  return fs.readFileSync(path.join(repoRoot, relativePath), "utf8");
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const slugSource = read("publications/threat_intelligence/pictograms/registry.ts");
const artSource = read("publications/threat_intelligence/pictograms/art.tsx");
const presentationSource = read("components/presentation-shell.tsx");
const articleSource = read("components/article-page.tsx");
const backgroundSource = read("publications/threat_intelligence/blog-defense/page-background.tsx");

for (const slug of [
  "the-balance-of-power-is-shifting",
  "how-our-newsroom-learns",
  "audit-aws-exposure-before-attackers-do",
  "audit-azure-blast-radius-before-attackers-do",
  "treat-openai-accounts-like-production-infrastructure",
  "how-to-play-games-securely",
]) {
  assert(slugSource.includes(`"${slug}"`), `Missing pictogram slug ${slug}`);
  assert(artSource.includes(`"${slug}"`), `Missing pictogram art registry entry for ${slug}`);
}

assert(slugSource.includes("PICTOGRAM_CYCLE_MS = 20_000"), "Expected shared 20-second pictogram cycle");
assert(presentationSource.includes("PictogramFigure"), "Presentation shell should render lead media through PictogramFigure");
assert(articleSource.includes("PictogramFigure"), "Article page should render lead media through PictogramFigure");
assert(artSource.includes("THREAT_INTELLIGENCE_PICTOGRAM_REGISTRY"), "Pictogram art registry should export slug map");
assert(backgroundSource.includes('from "../pictograms/registry"'), "Hero background should import shared pictogram timing");

console.log("Threat Intelligence pictogram static checks passed.");
