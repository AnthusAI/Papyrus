import fs from "node:fs";
import path from "node:path";
import type { Article, ArticleVideoAsset } from "../../lib/articles";

const DEFAULT_SEED_PROFILE = "default";
const SEED_PROFILE_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;

export type SeedHouseAd = {
  id: string;
  pageNumber: number;
  label: string;
  presetId?: "ad.region" | "ad.fullPage";
};

export type SeedEditionContent = {
  id: string;
  slug: string;
  title: string;
  description: string;
  publishDate: string;
  suppressNewsDeskAppendix?: boolean;
  video?: ArticleVideoAsset;
  houseAds?: SeedHouseAd[];
  articles: Article[];
};

export type SeedEditionContentSource = {
  profileId: string;
  sourcePath: string;
  content: SeedEditionContent;
};

let cachedSeedContentSource: SeedEditionContentSource | null = null;

export function getSeedEditionContentSource(): SeedEditionContentSource {
  if (cachedSeedContentSource) return cachedSeedContentSource;

  const profileId = resolveSeedProfileId(process.env.PAPYRUS_SEED_PROFILE);
  const sourcePath = resolveSeedEditionSourcePath(profileId);
  const content = parseSeedEditionContent(sourcePath);
  cachedSeedContentSource = { profileId, sourcePath, content };
  return cachedSeedContentSource;
}

function resolveSeedProfileId(value: string | undefined): string {
  const candidate = value?.trim().toLowerCase();
  if (!candidate) return DEFAULT_SEED_PROFILE;
  if (!SEED_PROFILE_PATTERN.test(candidate)) {
    throw new Error(`Invalid PAPYRUS_SEED_PROFILE '${value}'. Use lowercase letters, numbers, '-', or '_'.`);
  }
  return candidate;
}

function resolveSeedEditionSourcePath(profileId: string): string {
  const seedDir = path.join(process.cwd(), "amplify", "seed");
  const candidates = profileId === DEFAULT_SEED_PROFILE
    ? [path.join(seedDir, "seed-edition-content.json")]
    : [
        path.join(process.cwd(), "publications", profileId.replace(/-/g, "_"), "seed", "seed-edition-content.json"),
        path.join(seedDir, "profiles", profileId, "seed-edition-content.json"),
        path.join(seedDir, "seed-edition-content.json"),
      ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error(
    `Could not find seed edition content for profile '${profileId}'. Checked: ${candidates.join(", ")}`,
  );
}

function parseSeedEditionContent(filepath: string): SeedEditionContent {
  const raw = JSON.parse(fs.readFileSync(filepath, "utf8")) as Partial<SeedEditionContent> | null;
  if (!raw || typeof raw !== "object") throw new Error(`Seed content at ${filepath} must be a JSON object.`);

  assertRequiredString(raw.id, "id", filepath);
  assertRequiredString(raw.slug, "slug", filepath);
  assertRequiredString(raw.title, "title", filepath);
  assertRequiredString(raw.description, "description", filepath);
  assertRequiredString(raw.publishDate, "publishDate", filepath);
  if (!Array.isArray(raw.articles)) {
    throw new Error(`Seed content at ${filepath} must define articles as an array.`);
  }
  return raw as SeedEditionContent;
}

function assertRequiredString(value: unknown, field: string, filepath: string) {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Seed content at ${filepath} is missing required string field '${field}'.`);
  }
}
