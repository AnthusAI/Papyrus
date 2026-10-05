import fs from "node:fs";
import path from "node:path";
import { addToUserGroup, createAndSignUpUser, signInUser } from "@aws-amplify/seed";
import { Amplify, type ResourcesConfig } from "aws-amplify";
import { generateClient } from "aws-amplify/data";
import { signOut } from "aws-amplify/auth";
import YAML from "yaml";
import type { Schema } from "../data/resource";

const EDITOR_GROUP = "editor";
const ADMIN_GROUP = "admin";
const NEWSROOM_SECTIONS_CONFIG_PATH = path.join(process.cwd(), "corpora", "papyrus-newsroom-sections.yml");
const PUBLICATION_DOCTRINE_CONFIG_PATH = path.join(process.cwd(), "corpora", "papyrus-publication-doctrine.yml");
const REQUIRED_PROCEDURES_CONFIG_PATH = path.join(process.cwd(), "corpora", "papyrus-required-procedures.json");
const NEWSROOM_SECTION_TYPES = new Set(["canonical", "floating", "rotating"]);

type DataClient = ReturnType<typeof generateClient<Schema>>;
type NewsroomSectionSeed = {
  id: string;
  title: string;
  shortTitle: string;
  type: "canonical" | "floating" | "rotating";
  editorialMission: string;
  editorialPolicy: string;
  enabled: boolean;
  sortOrder: number;
  defaultArticleTypes: string[];
  defaultPageBudget: number | null;
  assignmentGuidance: string | null;
  killCriteria: string | null;
  visualGuidance: string | null;
};

type PublicationDoctrineSeed = {
  kind: "mission" | "policy";
  body: string[];
};

type ProcedureSeed = {
  key: string;
  title: string;
  category: string;
  description: string;
  versionLabel: string;
  tactusSource: string;
  parameterSchema: Record<string, unknown>;
  defaults: Record<string, unknown>;
};

const REQUIRED_CLI_PROCEDURE_KEYS = loadRequiredCliProcedureKeys();
const PROCEDURE_SOURCE_DIR = path.join(process.cwd(), "procedures", "newsroom");

function loadProcedureSeedSource(filename: string): string {
  const sourcePath = path.join(PROCEDURE_SOURCE_DIR, filename);
  const source = fs.readFileSync(sourcePath, "utf8").trimEnd();
  return `${source}\n`;
}

const PROCEDURE_SEED_BY_KEY: Record<string, ProcedureSeed> = {
  "ingestion.reference.register": {
    key: "ingestion.reference.register",
    title: "Ingest Reference",
    category: "ingestion",
    description: "Registers one reference intake payload and dispatches immediate enrichment workflow.",
    versionLabel: "starter",
    tactusSource: loadProcedureSeedSource("ingestion_reference_register.tac"),
    parameterSchema: {
      type: "object",
      required: ["externalItemId", "sourceUri"],
      properties: {
        externalItemId: { type: "string" },
        sourceUri: { type: "string" },
        title: { type: "string" },
        corpusKey: { type: "string" },
      },
    },
    defaults: {
      corpusKey: "threat-intelligence",
    },
  },
  "submissions.email.process": {
    key: "submissions.email.process",
    title: "Email Submission Processor",
    category: "ingestion",
    description: "Processes inbound submission emails into reference create/find/process intake for direct citations.",
    versionLabel: "starter",
    tactusSource: loadProcedureSeedSource("email_submission_processor.tac"),
    parameterSchema: {
      type: "object",
      required: ["message_id"],
      properties: {
        message_id: { type: "string" },
        corpus_key: { type: "string" },
        apply: { type: "boolean" },
      },
    },
    defaults: {
      corpus_key: "threat-intelligence",
      apply: true,
    },
  },
  "newsroom.research.explorer": {
    key: "newsroom.research.explorer",
    title: "Newsroom Research Explorer",
    category: "newsroom",
    description: "Builds structured research packets for assignment-backed newsroom workflows.",
    versionLabel: "starter",
    tactusSource: loadProcedureSeedSource("research_explorer.tac"),
    parameterSchema: {
      type: "object",
      required: ["corpus_key"],
      properties: {
        assignment_item_id: { type: "string" },
        assignment_json: { type: "object" },
        corpus_key: { type: "string" },
        context_profile: { type: "string" },
        research_mode: { type: "string" },
        research_questions: { type: "string" },
        max_evidence_items: { type: "number" },
      },
    },
    defaults: {
      context_profile: "researcher",
      research_mode: "source_discovery",
      max_evidence_items: 20,
    },
  },
  "newsroom.rotating.section.selector": {
    key: "newsroom.rotating.section.selector",
    title: "Newsroom Rotating Desk Selector",
    category: "newsroom",
    description: "Recommends one optional floating/rotating desk for an edition using recent desk usage.",
    versionLabel: "starter",
    tactusSource: loadProcedureSeedSource("rotating_section_selector.tac"),
    parameterSchema: {
      type: "object",
      required: ["edition_id", "accepted_theme"],
      properties: {
        edition_id: { type: "string" },
        accepted_theme: { type: "string" },
        coverage_key: { type: "string" },
        candidate_sections_json: { type: "string" },
        recent_usage_json: { type: "string" },
        steering_notes: { type: "string" },
      },
    },
    defaults: {},
  },
  "newsroom.reporting.context": {
    key: "newsroom.reporting.context",
    title: "Newsroom Reporting Context",
    category: "newsroom",
    description: "Builds structured reporting context packets from assignment-backed runs.",
    versionLabel: "starter",
    tactusSource: loadProcedureSeedSource("reporter.tac"),
    parameterSchema: {
      type: "object",
      required: ["corpus_key"],
      properties: {
        assignment_item_id: { type: "string" },
        assignment_json: { type: "object" },
        corpus_key: { type: "string" },
        context_profile: { type: "string" },
        source_research_assignment_id: { type: "string" },
        source_research_packet_id: { type: "string" },
        source_research_packet_path: { type: "string" },
      },
    },
    defaults: {
      context_profile: "reporting",
    },
  },
  "newsroom.reference.summarization": {
    key: "newsroom.reference.summarization",
    title: "Newsroom Reference Summarization",
    category: "newsroom",
    description: "Generates source-voice reference summaries for curation metadata and summary messages.",
    versionLabel: "starter",
    tactusSource: loadProcedureSeedSource("reference_summarization.tac"),
    parameterSchema: {
      type: "object",
      required: ["mode", "source_text"],
      properties: {
        mode: { type: "string" },
        source_text: { type: "string" },
        max_tokens: { type: "number" },
        reference_title: { type: "string" },
        source_uri: { type: "string" },
        known_title: { type: "string" },
        known_subtitle: { type: "string" },
        media_type: { type: "string" },
        doctrine_context_text: { type: "string" },
        model: { type: "string" },
        prompt_version: { type: "string" },
      },
    },
    defaults: {
      mode: "reference_summary",
      max_tokens: 500,
      model: "gpt-5.4-mini",
    },
  },
  "ontology.relationship-explainer": {
    key: "ontology.relationship-explainer",
    title: "Ontology Relationship Explainer",
    category: "ontology",
    description: "Generates contextual explanations for SemanticRelation rows from resolved Papyrus graph context.",
    versionLabel: "starter",
    tactusSource: loadProcedureSeedSource("ontology_relationship_explainer.tac"),
    parameterSchema: {
      type: "object",
      required: ["context_json"],
      properties: {
        context_json: { type: "object" },
      },
    },
    defaults: {},
  },
  "ontology.concept-profiler": {
    key: "ontology.concept-profiler",
    title: "Ontology Concept Profiler",
    category: "ontology",
    description: "Synthesizes generated Concept profiles from fresh relation-specific explanations.",
    versionLabel: "starter",
    tactusSource: loadProcedureSeedSource("ontology_concept_profiler.tac"),
    parameterSchema: {
      type: "object",
      required: ["context_json"],
      properties: {
        context_json: { type: "object" },
      },
    },
    defaults: {},
  },
};

const PROCEDURE_SEEDS: ProcedureSeed[] = [
  PROCEDURE_SEED_BY_KEY["ingestion.reference.register"],
  ...REQUIRED_CLI_PROCEDURE_KEYS.map((key) => {
    const seed = PROCEDURE_SEED_BY_KEY[key];
    if (!seed) throw new Error(`Missing ProcedureSeed for required CLI procedure '${key}'.`);
    return seed;
  }),
];

let cachedClient: DataClient | null = null;

function getSeedClient(): DataClient {
  if (!cachedClient) cachedClient = generateClient<Schema>({ authMode: "userPool" });
  return cachedClient;
}

async function main() {
  Amplify.configure(loadSeedAmplifyOutputs());
  await signInSeedEditor();
  const seededAt = new Date().toISOString();

  try {
    await seedNewsroomSections(seededAt);
    await seedPublicationDoctrine(seededAt);
    await seedProcedureDefinitions(seededAt);
    console.log("Seeded sections, doctrine and procedures. Seed articles with: poetry run papyrus content seed-edition");
  } finally {
    await signOut();
  }
}

function loadSeedAmplifyOutputs(): ResourcesConfig {
  const outputsPath = path.join(process.cwd(), "amplify_outputs.json");
  if (!fs.existsSync(outputsPath)) {
    throw new Error("Missing amplify_outputs.json. Run `npm run sandbox` before seeding.");
  }
  return JSON.parse(fs.readFileSync(outputsPath, "utf8")) as ResourcesConfig;
}

async function signInSeedEditor() {
  const password = process.env.PAPYRUS_SEED_PASSWORD ?? "PapyrusSeed1!";
  const email = process.env.PAPYRUS_SEED_EMAIL ?? "papyrus-seed-editor@example.com";
  const username = process.env.PAPYRUS_SEED_USERNAME ?? email;

  try {
    await createAndSignUpUser({
      signInAfterCreation: false,
      username,
      password,
      signInFlow: "Password",
      userAttributes: {
        email,
      },
    });
  } catch (error) {
    if (!isExpectedExistingUserError(error)) throw error;
  }

  await addToUserGroup({ username }, EDITOR_GROUP);
  await addToUserGroup({ username }, ADMIN_GROUP);
  const signedIn = await signInUser({
    username,
    password,
    signInFlow: "Password",
  });

  if (!signedIn) {
    throw new Error(`Could not sign in seed editor ${username}. Check PAPYRUS_SEED_PASSWORD.`);
  }
}

async function seedNewsroomSections(importedAt: string) {
  const sections = loadNewsroomSectionSeeds();
  for (const section of sections) {
    await upsert("NewsroomSection", {
      id: section.id,
      title: section.title,
      shortTitle: section.shortTitle,
      type: section.type,
      editorialMission: section.editorialMission,
      editorialPolicy: section.editorialPolicy,
      enabled: section.enabled,
      enabledStatus: section.enabled ? "enabled" : "disabled",
      sortOrder: section.sortOrder,
      defaultArticleTypes: section.defaultArticleTypes,
      defaultPageBudget: section.defaultPageBudget,
      assignmentGuidance: section.assignmentGuidance,
      killCriteria: section.killCriteria,
      visualGuidance: section.visualGuidance,
      createdAt: importedAt,
      updatedAt: importedAt,
    });
  }
}

async function seedPublicationDoctrine(importedAt: string) {
  const doctrine = loadPublicationDoctrineSeeds();
  for (const entry of doctrine) {
    const details =
      entry.kind === "mission"
        ? {
            id: "item-editorial-doctrine-mission-v1",
            lineageId: "item-editorial-doctrine-mission",
            slug: "editorial-doctrine-mission",
            title: "Editorial Mission",
          }
        : {
            id: "item-editorial-doctrine-policy-v1",
            lineageId: "item-editorial-doctrine-policy",
            slug: "editorial-doctrine-policy",
            title: "Editorial Policy",
          };
    await upsert("Item", {
      id: details.id,
      lineageId: details.lineageId,
      versionNumber: 1,
      versionState: "current",
      versionCreatedAt: importedAt,
      versionCreatedBy: "amplify-seed",
      type: "doctrine",
      status: "private",
      typeStatus: "doctrine#private",
      slug: details.slug,
      title: details.title,
      body: entry.body,
      updatedAt: importedAt,
    });
  }
}

async function seedProcedureDefinitions(importedAt: string) {
  for (const seed of PROCEDURE_SEEDS) {
    const procedureId = `procedure-definition-${safeProcedureId(seed.key)}`;
    const versionId = `procedure-version-${safeProcedureId(seed.key)}-1`;
    await upsert("ProcedureDefinition", {
      id: procedureId,
      procedureKey: seed.key,
      title: seed.title,
      category: seed.category,
      description: seed.description,
      enabled: true,
      enabledStatus: "enabled",
      currentVersionId: versionId,
      createdBy: "amplify-seed",
      createdAt: importedAt,
      updatedBy: "amplify-seed",
      updatedAt: importedAt,
      newsroomFeedKey: "procedures",
    });
    await upsert("ProcedureVersion", {
      id: versionId,
      procedureId,
      procedureKey: seed.key,
      versionNumber: 1,
      status: "published",
      isCurrent: true,
      label: seed.versionLabel,
      tactusSource: seed.tactusSource,
      parameterSchema: toAwsJson(seed.parameterSchema),
      defaults: toAwsJson(seed.defaults),
      changelog: "Seeded starter procedure.",
      createdBy: "amplify-seed",
      createdAt: importedAt,
      updatedBy: "amplify-seed",
      updatedAt: importedAt,
    });
  }
}

function safeProcedureId(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "procedure";
}

function loadRequiredCliProcedureKeys(configPath = REQUIRED_PROCEDURES_CONFIG_PATH): string[] {
  if (!fs.existsSync(configPath)) return [];
  const parsed = JSON.parse(fs.readFileSync(configPath, "utf8")) as {
    requiredCliProcedures?: Record<string, unknown>;
  };
  const map = parsed?.requiredCliProcedures;
  if (!map || typeof map !== "object") {
    throw new Error(`Invalid required procedures config file: ${configPath}`);
  }
  const keys = Array.from(new Set(Object.values(map).map((value) => String(value ?? "").trim()).filter(Boolean)));
  if (!keys.length) {
    throw new Error(`No required CLI procedure keys were configured in ${configPath}.`);
  }
  return keys;
}

function loadNewsroomSectionSeeds(configPath = NEWSROOM_SECTIONS_CONFIG_PATH): NewsroomSectionSeed[] {
  const parsed = YAML.parse(fs.readFileSync(configPath, "utf8")) as {
    schemaVersion?: number;
    sections?: Array<Record<string, unknown>>;
  };
  if (!parsed || parsed.schemaVersion !== 1 || !Array.isArray(parsed.sections)) {
    throw new Error(`Invalid newsroom section seed file: ${configPath}`);
  }
  return parsed.sections.map((entry, index) => normalizeNewsroomSectionSeed(entry, index, configPath));
}

function loadPublicationDoctrineSeeds(configPath = PUBLICATION_DOCTRINE_CONFIG_PATH): PublicationDoctrineSeed[] {
  if (!fs.existsSync(configPath)) return [];
  const parsed = YAML.parse(fs.readFileSync(configPath, "utf8")) as {
    schemaVersion?: number;
    doctrine?: Array<Record<string, unknown>>;
  };
  if (!parsed || parsed.schemaVersion !== 1 || !Array.isArray(parsed.doctrine)) {
    throw new Error(`Invalid publication doctrine seed file: ${configPath}`);
  }
  const entries = parsed.doctrine.map((entry, index) => normalizePublicationDoctrineSeed(entry, index, configPath));
  const byKind = new Map(entries.map((entry) => [entry.kind, entry]));
  for (const kind of ["mission", "policy"] as const) {
    if (!byKind.has(kind)) {
      throw new Error(`Publication doctrine seed file ${configPath} is missing kind '${kind}'.`);
    }
  }
  return [byKind.get("mission")!, byKind.get("policy")!];
}

function normalizeNewsroomSectionSeed(entry: Record<string, unknown>, index: number, configPath: string): NewsroomSectionSeed {
  const id = String(entry.id ?? "").trim();
  if (!id) throw new Error(`Newsroom section at index ${index} in ${configPath} is missing id.`);
  const title = requiredText(entry.title, `title for section ${id}`);
  const rawTypeValue = String(entry.type ?? "").trim().toLowerCase();
  if (!NEWSROOM_SECTION_TYPES.has(rawTypeValue)) {
    throw new Error(`Newsroom section ${id} in ${configPath} has unsupported type '${String(entry.type ?? "")}'.`);
  }
  const typeValue = rawTypeValue === "rotating" ? "floating" : rawTypeValue;
  return {
    id,
    title,
    shortTitle: requiredText(entry.shortTitle, `shortTitle for section ${id}`),
    type: typeValue as NewsroomSectionSeed["type"],
    editorialMission: requiredText(entry.editorialMission, `editorialMission for section ${id}`),
    editorialPolicy: requiredText(entry.editorialPolicy, `editorialPolicy for section ${id}`),
    enabled: typeof entry.enabled === "boolean" ? entry.enabled : true,
    sortOrder: positiveInteger(entry.sortOrder, index + 1),
    defaultArticleTypes: normalizeStringList(entry.defaultArticleTypes),
    defaultPageBudget: optionalInteger(entry.defaultPageBudget),
    assignmentGuidance: optionalText(entry.assignmentGuidance),
    killCriteria: optionalText(entry.killCriteria),
    visualGuidance: optionalText(entry.visualGuidance),
  };
}

function normalizePublicationDoctrineSeed(
  entry: Record<string, unknown>,
  index: number,
  configPath: string,
): PublicationDoctrineSeed {
  const kindValue = String(entry.kind ?? "").trim().toLowerCase();
  if (kindValue !== "mission" && kindValue !== "policy") {
    throw new Error(
      `Publication doctrine entry at index ${index} in ${configPath} has unsupported kind '${String(entry.kind ?? "")}'.`,
    );
  }
  const body = normalizeStringList(entry.body);
  if (!body.length) {
    throw new Error(`Publication doctrine entry '${kindValue}' in ${configPath} requires non-empty body.`);
  }
  return {
    kind: kindValue,
    body,
  };
}

function requiredText(value: unknown, label: string): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) throw new Error(`Missing ${label} in ${path.basename(NEWSROOM_SECTIONS_CONFIG_PATH)}.`);
  return normalized;
}

function optionalText(value: unknown): string | null {
  const normalized = String(value ?? "").trim();
  return normalized ? normalized : null;
}

function normalizeStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => optionalText(entry))
    .filter((entry): entry is string => Boolean(entry));
}

function optionalInteger(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : null;
}

function positiveInteger(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

async function upsert(modelName: keyof DataClient["models"], record: Record<string, unknown>) {
  const model = (getSeedClient().models as Record<string, unknown>)[String(modelName)] as {
    get(input: { id: string }, options: { authMode: "userPool" }): Promise<{ data?: unknown; errors?: unknown[] }>;
    create(input: Record<string, unknown>, options: { authMode: "userPool" }): Promise<{ errors?: unknown[] }>;
    update(input: Record<string, unknown>, options: { authMode: "userPool" }): Promise<{ errors?: unknown[] }>;
  };
  const current = await model.get({ id: String(record.id) }, { authMode: "userPool" });
  assertNoGraphQLErrors(current.errors);

  const response = current.data
    ? await model.update(record, { authMode: "userPool" })
    : await model.create(record, { authMode: "userPool" });
  assertNoGraphQLErrors(response.errors);
}

function isExpectedExistingUserError(error: unknown): boolean {
  const text = `${(error as { name?: string }).name ?? ""} ${(error as { message?: string }).message ?? ""}`;
  return text.includes("UsernameExists") || text.includes("already exists");
}

function assertNoGraphQLErrors(errors: unknown[] | null | undefined): void {
  if (!errors?.length) return;
  throw new Error(`Amplify seed GraphQL request failed: ${JSON.stringify(errors)}`);
}

function toAwsJson(value: unknown): string {
  return JSON.stringify(value);
}

try {
  await main();
} catch (error) {
  const detail = formatUnknownError(error);
  console.error(`Amplify seed failed: ${detail}`);
  if (error instanceof Error) throw error;
  throw new Error(detail);
}

function formatUnknownError(error: unknown): string {
  if (error instanceof Error) {
    const stack = typeof error.stack === "string" && error.stack.trim() ? error.stack : null;
    return stack ?? `${error.name}: ${error.message}`;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}
