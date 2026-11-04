import "server-only";

import fs from "node:fs";
import path from "node:path";
import { parse } from "yaml";

export type PublicPlaceholderSectionType = "canonical" | "floating";

export type PublicPlaceholderSection = {
  id: string;
  title: string;
  shortTitle: string;
  type: PublicPlaceholderSectionType;
  sortOrder: number;
};

export type PublicPlaceholderTopic = {
  key: string;
  title: string;
  shortTitle: string;
  description: string;
  rank: number;
};

const NEWSROOM_SECTIONS_CONFIG_PATH = path.join(process.cwd(), "corpora", "threat-intelligence-newsroom-sections.yml");
const PUBLIC_TOPICS_CONFIG_PATH = path.join(process.cwd(), "corpora", "papyrus-public-topics.yml");

export function loadPublicPlaceholderSections(): PublicPlaceholderSection[] {
  const parsed = readYamlRecord(NEWSROOM_SECTIONS_CONFIG_PATH);
  const sections = Array.isArray(parsed.sections) ? parsed.sections : [];
  return sections
    .map((entry, index) => normalizePublicSection(entry, index))
    .filter((section): section is PublicPlaceholderSection => section !== null)
    .sort((left, right) => left.sortOrder - right.sortOrder || left.title.localeCompare(right.title));
}

export function loadPublicPlaceholderTopics(): PublicPlaceholderTopic[] {
  const parsed = readYamlRecord(PUBLIC_TOPICS_CONFIG_PATH);
  const topics = Array.isArray(parsed.topics) ? parsed.topics : [];
  return topics
    .map((entry, index) => normalizePublicTopic(entry, index))
    .sort((left, right) => left.rank - right.rank || left.title.localeCompare(right.title));
}

function readYamlRecord(filePath: string): Record<string, unknown> {
  const parsed = parse(fs.readFileSync(filePath, "utf8"));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`Invalid public placeholder config: ${filePath}`);
  }
  return parsed as Record<string, unknown>;
}

function normalizePublicSection(entry: unknown, index: number): PublicPlaceholderSection | null {
  const record = objectRecord(entry);
  const enabled = record.enabled;
  if (enabled === false) return null;

  const id = requiredString(record.id, `sections[${index}].id`);
  const title = requiredString(record.title, `sections[${index}].title`);
  const shortTitle = requiredString(record.shortTitle, `sections[${index}].shortTitle`);
  const rawType = requiredString(record.type, `sections[${index}].type`);
  const type = rawType === "canonical" ? "canonical" : rawType === "floating" || rawType === "rotating" ? "floating" : null;
  if (!type) throw new Error(`Unsupported public section type '${rawType}' for ${id}`);

  return {
    id,
    title,
    shortTitle,
    type,
    sortOrder: numberValue(record.sortOrder) ?? index + 1,
  };
}

function normalizePublicTopic(entry: unknown, index: number): PublicPlaceholderTopic {
  const record = objectRecord(entry);
  return {
    key: requiredString(record.key, `topics[${index}].key`),
    title: requiredString(record.title, `topics[${index}].title`),
    shortTitle: requiredString(record.shortTitle, `topics[${index}].shortTitle`),
    description: requiredString(record.description, `topics[${index}].description`),
    rank: numberValue(record.rank) ?? index + 1,
  };
}

function objectRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  throw new Error(`Missing required public placeholder value: ${label}`);
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
