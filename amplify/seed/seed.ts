import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { addToUserGroup, createAndSignUpUser, signInUser } from "@aws-amplify/seed";
import { Amplify, type ResourcesConfig } from "aws-amplify";
import { generateClient } from "aws-amplify/data";
import { signOut } from "aws-amplify/auth";
import { getProperties, uploadData } from "aws-amplify/storage";
import YAML from "yaml";
import type { Schema } from "../data/resource";
import type { Article, ArticleImageAsset, ArticleVideoAsset } from "../../lib/articles";
import { getSeedEditionConfig, getSeedEditionProfileInfo, seedEditionArticles } from "./seed-edition-content";
import { getSeedEditionContentSource } from "./seed-profile";

const EDITOR_GROUP = "editor";
const ADMIN_GROUP = "admin";
const NEWSROOM_SECTIONS_CONFIG_PATH = path.join(process.cwd(), "corpora", "papyrus-newsroom-sections.yml");
const PUBLICATION_DOCTRINE_CONFIG_PATH = path.join(process.cwd(), "corpora", "papyrus-publication-doctrine.yml");
const REQUIRED_PROCEDURES_CONFIG_PATH = path.join(process.cwd(), "corpora", "papyrus-required-procedures.json");
const NEWSROOM_SECTION_TYPES = new Set(["canonical", "floating", "rotating"]);
type UploadedImageThemeVariants = {
  dark?: {
    storagePath: string;
  };
};

type DataClient = ReturnType<typeof generateClient<Schema>>;
type GraphQLClient = {
  graphql: (options: {
    query: string;
    variables?: Record<string, unknown>;
    authMode?: "userPool";
  }) => Promise<{
    data?: Record<string, unknown> | null;
    errors?: unknown[] | null;
  }>;
};
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

const CREATE_MODEL_ATTACHMENT_UPLOAD_MUTATION = `
  mutation CreateModelAttachmentUpload(
    $ownerKind: String!
    $ownerId: ID!
    $ownerLineageId: ID
    $ownerVersionNumber: Int
    $ownerVersionKey: String
    $role: String!
    $sortKey: String
    $filename: String!
    $mediaType: String!
    $byteSize: Int!
    $sha256: String
    $importRunId: ID
    $status: String
  ) {
    createModelAttachmentUpload(
      ownerKind: $ownerKind
      ownerId: $ownerId
      ownerLineageId: $ownerLineageId
      ownerVersionNumber: $ownerVersionNumber
      ownerVersionKey: $ownerVersionKey
      role: $role
      sortKey: $sortKey
      filename: $filename
      mediaType: $mediaType
      byteSize: $byteSize
      sha256: $sha256
      importRunId: $importRunId
      status: $status
    ) {
      ok
      uploadId
      uploadUrl
      method
      requiredHeaders
      storagePath
    }
  }
`;

const COMPLETE_MODEL_ATTACHMENT_UPLOAD_MUTATION = `
  mutation CompleteModelAttachmentUpload(
    $uploadId: String!
    $ownerKind: String!
    $ownerId: ID!
    $ownerLineageId: ID
    $ownerVersionNumber: Int
    $ownerVersionKey: String
    $role: String!
    $sortKey: String
    $filename: String!
    $mediaType: String!
    $byteSize: Int!
    $sha256: String
    $importRunId: ID
    $status: String
  ) {
    completeModelAttachmentUpload(
      uploadId: $uploadId
      ownerKind: $ownerKind
      ownerId: $ownerId
      ownerLineageId: $ownerLineageId
      ownerVersionNumber: $ownerVersionNumber
      ownerVersionKey: $ownerVersionKey
      role: $role
      sortKey: $sortKey
      filename: $filename
      mediaType: $mediaType
      byteSize: $byteSize
      sha256: $sha256
      importRunId: $importRunId
      status: $status
    ) {
      id
      ownerKind
      ownerId
      ownerLineageId
      ownerVersionNumber
      ownerVersionKey
      role
      sortKey
      storagePath
      filename
      mediaType
      byteSize
      sha256
      etag
      importRunId
      createdAt
      updatedAt
      status
    }
  }
`;

let cachedClient: DataClient | null = null;

function getSeedClient(): DataClient {
  if (!cachedClient) cachedClient = generateClient<Schema>({ authMode: "userPool" });
  return cachedClient;
}

async function main() {
  Amplify.configure(loadSeedAmplifyOutputs());
  await signInSeedEditor();
  const seedProfile = getSeedEditionProfileInfo();
  console.log(`seed\tedition-profile\t${seedProfile.id}\t${seedProfile.sourcePath}`);
  const editionConfig = getSeedEditionConfig();

  try {
    const orderedArticles = orderArticles(seedEditionArticles, editionConfig.articleOrder);
    const editionRecord = withVersionFields({
      id: editionConfig.id,
      slug: editionConfig.slug,
      title: editionConfig.title,
      status: "published",
      editionDate: editionConfig.publishDate,
      publishedAt: editionConfig.publishedAt,
      description: editionConfig.description,
      layoutPlan: toAwsJson(editionConfig.layoutPlan),
      metadata: toAwsJson(editionConfig.metadata),
    }, {
      lineageId: editionConfig.id,
      versionCreatedAt: editionConfig.publishedAt,
      versionCreatedBy: "amplify-seed",
      changeReason: "fixture seed",
    });
    await upsert("Edition", editionRecord);
    await upsert("PublishedEdition", {
      id: publishedEditionId(editionConfig.id),
      sourceEditionId: editionRecord.id,
      editionLineageId: editionRecord.lineageId,
      versionNumber: editionRecord.versionNumber,
      slug: editionConfig.slug,
      title: editionConfig.title,
      status: "published",
      editionDate: editionConfig.publishDate,
      publishedAt: editionConfig.publishedAt,
      description: editionConfig.description,
      layoutPlan: toAwsJson(editionConfig.layoutPlan),
      metadata: toAwsJson(editionConfig.metadata),
    });
    await clearEditionItemLinks(editionConfig.id, publishedEditionId(editionConfig.id));
    await seedNewsroomSections(editionConfig.publishedAt);
    await seedPublicationDoctrine(editionConfig.publishedAt);
    await seedProcedureDefinitions(editionConfig.publishedAt);

    for (const [index, article] of orderedArticles.entries()) {
      await seedArticle(article, index, editionConfig);
    }

    const editionVideo = getSeedEditionContentSource().content.video;
    if (editionVideo) {
      const editionVideoRecord = await buildSeedEditionVideoMetadata(editionConfig.slug, editionVideo);
      const updatedMetadata = {
        ...editionConfig.metadata,
        editionVideo: editionVideoRecord,
      };
      if (JSON.stringify(updatedMetadata) !== JSON.stringify(editionConfig.metadata)) {
        await upsert("Edition", {
          ...editionRecord,
          metadata: toAwsJson(updatedMetadata),
        });
        await upsert("PublishedEdition", {
          id: publishedEditionId(editionConfig.id),
          sourceEditionId: editionRecord.id,
          editionLineageId: editionRecord.lineageId,
          versionNumber: editionRecord.versionNumber,
          slug: editionConfig.slug,
          title: editionConfig.title,
          status: "published",
          editionDate: editionConfig.publishDate,
          publishedAt: editionConfig.publishedAt,
          description: editionConfig.description,
          layoutPlan: toAwsJson(editionConfig.layoutPlan),
          metadata: toAwsJson(updatedMetadata),
        });
      }
    }

    console.log(`Seeded ${orderedArticles.length} articles into Amplify Data and Storage.`);
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

type SeedEditionConfig = ReturnType<typeof getSeedEditionConfig>;

async function seedArticle(article: Article, index: number, editionConfig: SeedEditionConfig) {
  const itemId = `item-${article.slug}`;
  const publishedId = publishedItemId(itemId);
  const sectionSlug = slugify(article.section);
  const tagId = `tag-${sectionSlug}`;
  const sortKey = `${String(index + 1).padStart(3, "0")}#${article.slug}`;
  const bodyText = normalizeArticleBodyText(article.body);
  const excerptText = normalizeOptionalText(article.excerpt);
  const emptyEditorial = contentAttachmentEditorialRecord(null, null);

  const itemRecord = withVersionFields({
    id: itemId,
    type: "article",
    status: "published",
    typeStatus: "article#published",
    slug: article.slug,
    shortSlug: article.shortSlug,
    section: article.section,
    sectionStatus: `${sectionSlug}#published`,
    title: article.headline,
    headline: article.headline,
    deck: article.deck,
    body: [],
    byline: article.byline,
    dateline: article.dateline,
    publishedAt: editionConfig.publishedAt,
    editionDate: editionConfig.publishDate,
    sortTitle: article.headline,
    pullQuotes: article.pullQuotes ?? [],
    layout: toAwsJson({ source: "fixture" }),
    editorial: toAwsJson(emptyEditorial),
  }, {
    lineageId: itemId,
    versionCreatedAt: editionConfig.publishedAt,
    versionCreatedBy: "amplify-seed",
    changeReason: "fixture seed",
  });
  await upsert("Item", itemRecord);
  const publishedRecord = {
    id: publishedId,
    sourceItemId: itemRecord.id,
    itemLineageId: itemRecord.lineageId,
    versionNumber: itemRecord.versionNumber,
    type: "article",
    status: "published",
    typeStatus: "article#published",
    slug: article.slug,
    shortSlug: article.shortSlug,
    section: article.section,
    sectionStatus: `${sectionSlug}#published`,
    title: article.headline,
    headline: article.headline,
    deck: article.deck,
    body: [],
    byline: article.byline,
    dateline: article.dateline,
    publishedAt: editionConfig.publishedAt,
    editionDate: editionConfig.publishDate,
    sortTitle: article.headline,
    pullQuotes: article.pullQuotes ?? [],
    layout: toAwsJson({ source: "fixture" }),
    editorial: toAwsJson(emptyEditorial),
  };
  await upsert("PublishedItem", publishedRecord);

  const itemBodyAttachment = bodyText
    ? await upsertSeedTextAttachment({
      ownerKind: "item",
      ownerId: itemId,
      ownerLineageId: itemId,
      ownerVersionNumber: 1,
      ownerVersionKey: `item#${itemId}`,
      role: "item_body",
      sortKey: "body",
      filename: "body.md",
      mediaType: "text/markdown",
      content: bodyText,
      now: editionConfig.publishedAt,
      importRunId: null,
    })
    : null;
  const itemExcerptAttachment = excerptText
    ? await upsertSeedTextAttachment({
      ownerKind: "item",
      ownerId: itemId,
      ownerLineageId: itemId,
      ownerVersionNumber: 1,
      ownerVersionKey: `item#${itemId}`,
      role: "item_excerpt",
      sortKey: "excerpt",
      filename: "excerpt.txt",
      mediaType: "text/plain",
      content: excerptText,
      now: editionConfig.publishedAt,
      importRunId: null,
    })
    : null;
  const publishedBodyAttachment = bodyText
    ? await upsertSeedTextAttachment({
      ownerKind: "publishedItem",
      ownerId: publishedId,
      ownerLineageId: itemId,
      ownerVersionNumber: 1,
      ownerVersionKey: `publishedItem#${publishedId}`,
      role: "published_item_body",
      sortKey: "body",
      filename: "body.md",
      mediaType: "text/markdown",
      content: bodyText,
      now: editionConfig.publishedAt,
      importRunId: null,
    })
    : null;
  const publishedExcerptAttachment = excerptText
    ? await upsertSeedTextAttachment({
      ownerKind: "publishedItem",
      ownerId: publishedId,
      ownerLineageId: itemId,
      ownerVersionNumber: 1,
      ownerVersionKey: `publishedItem#${publishedId}`,
      role: "published_item_excerpt",
      sortKey: "excerpt",
      filename: "excerpt.txt",
      mediaType: "text/plain",
      content: excerptText,
      now: editionConfig.publishedAt,
      importRunId: null,
    })
    : null;
  const itemEditorial = contentAttachmentEditorialRecord(itemBodyAttachment, itemExcerptAttachment);
  const publishedEditorial = contentAttachmentEditorialRecord(publishedBodyAttachment, publishedExcerptAttachment);
  await upsert("Item", withVersionFields({
    ...itemRecord,
    editorial: toAwsJson(itemEditorial),
  }, {
    lineageId: itemId,
    versionCreatedAt: editionConfig.publishedAt,
    versionCreatedBy: "amplify-seed",
    changeReason: "fixture seed",
  }));
  await upsert("PublishedItem", {
    ...publishedRecord,
    editorial: toAwsJson(publishedEditorial),
  });

  await upsert("Tag", {
    id: tagId,
    slug: sectionSlug,
    label: article.section,
    type: "section",
  });

  await upsert("ItemTag", {
    id: `item-tag-${article.slug}-${sectionSlug}`,
    itemId,
    tagId,
    itemType: "article",
    itemStatus: "published",
    tagSlug: sectionSlug,
    publishedAt: editionConfig.publishedAt,
  });

  await upsert("EditionItem", {
    id: `${editionConfig.id}-${article.slug}`,
    editionId: editionConfig.id,
    editionLineageId: editionConfig.id,
    itemId,
    itemLineageId: itemId,
    placementKey: `front:${index + 1}`,
    sortKey,
    pageNumber: 1,
    priority: index + 1,
    metadata: toAwsJson({}),
  });
  await upsert("PublishedEditionItem", {
    id: `${publishedEditionId(editionConfig.id)}-${article.slug}`,
    publishedEditionId: publishedEditionId(editionConfig.id),
    publishedItemId: publishedId,
    sourceEditionItemId: `${editionConfig.id}-${article.slug}`,
    sourceEditionId: editionConfig.id,
    sourceItemId: itemId,
    editionLineageId: editionConfig.id,
    itemLineageId: itemId,
    placementKey: `front:${index + 1}`,
    sortKey,
    pageNumber: 1,
    priority: index + 1,
    metadata: toAwsJson({}),
  });

  await clearArticleMediaAssets(itemId, publishedItemId(itemId));

  const imageAssets = getSeedArticleImageAssets(article);
  for (const [assetIndex, asset] of imageAssets.entries()) {
    const uploaded = await uploadSeedImage(article, asset, assetIndex);
    const mediaId = `media-${article.slug}-${assetIndex}`;
    const mediaSortKey = `${String(assetIndex + 1).padStart(3, "0")}#${asset.id}`;
    await upsert("MediaAsset", {
      id: mediaId,
      itemId,
      type: "image",
      role: (asset.roles ?? ["lead", "continuation", "continuationInset"]).join(","),
      sortKey: mediaSortKey,
      storagePath: uploaded.storagePath,
      externalUrl: asset.src,
      alt: asset.alt,
      caption: asset.caption ?? asset.credit,
      credit: asset.credit,
      width: uploaded.width,
      height: uploaded.height,
      aspectRatio: asset.layout?.aspectRatio,
      focalX: asset.layout?.focalPoint?.x,
      focalY: asset.layout?.focalPoint?.y,
      minHeight: asset.layout?.minHeight,
      preferredHeight: asset.layout?.preferredHeight,
      maxHeight: asset.layout?.maxHeight,
      crop: asset.layout?.crop,
      wrapsText: asset.layout?.wrapsText,
      metadata: toAwsJson({
        ...getMediaMetadata(asset, uploaded.themeVariants),
        ...(!asset.src ? { pictogramSlug: article.slug } : {}),
      }),
    });
    await upsert("PublishedMediaAsset", {
      id: `published-${mediaId}`,
      sourceMediaAssetId: mediaId,
      publishedItemId: publishedItemId(itemId),
      sourceItemId: itemId,
      itemLineageId: itemId,
      type: "image",
      role: (asset.roles ?? ["lead", "continuation", "continuationInset"]).join(","),
      sortKey: mediaSortKey,
      storagePath: uploaded.storagePath,
      externalUrl: asset.src,
      alt: asset.alt,
      caption: asset.caption ?? asset.credit,
      credit: asset.credit,
      width: uploaded.width,
      height: uploaded.height,
      aspectRatio: asset.layout?.aspectRatio,
      focalX: asset.layout?.focalPoint?.x,
      focalY: asset.layout?.focalPoint?.y,
      minHeight: asset.layout?.minHeight,
      preferredHeight: asset.layout?.preferredHeight,
      maxHeight: asset.layout?.maxHeight,
      crop: asset.layout?.crop,
      wrapsText: asset.layout?.wrapsText,
      metadata: toAwsJson({
        ...getMediaMetadata(asset, uploaded.themeVariants),
        ...(!asset.src ? { pictogramSlug: article.slug } : {}),
      }),
    });
  }

  const videoAsset = getSeedArticleVideoAsset(article);
  if (videoAsset) {
    const videoIndex = imageAssets.length;
    const mediaId = `media-${article.slug}-video`;
    const mediaSortKey = `${String(videoIndex + 1).padStart(3, "0")}#${article.slug}-lead-video`;
    let storagePath: string | undefined;
    let uploadedVideoThemeVariants: UploadedVideoThemeVariants | undefined;
    if (shouldSeedVideoUploads()) {
      const uploaded = await uploadSeedVideo(article, videoAsset);
      storagePath = uploaded.storagePath;
      uploadedVideoThemeVariants = uploaded.themeVariants;
    }
    const videoMetadata = getVideoMediaMetadata(videoAsset, uploadedVideoThemeVariants);
    const commonVideo = {
      type: "video" as const,
      role: "lead",
      sortKey: mediaSortKey,
      storagePath,
      externalUrl: videoAsset.src,
      alt: videoAsset.alt,
      caption: videoAsset.caption ?? videoAsset.credit,
      credit: videoAsset.credit,
      aspectRatio: 16 / 9,
      metadata: toAwsJson(videoMetadata),
    };
    await upsert("MediaAsset", {
      id: mediaId,
      itemId,
      ...commonVideo,
    });
    await upsert("PublishedMediaAsset", {
      id: `published-${mediaId}`,
      sourceMediaAssetId: mediaId,
      publishedItemId: publishedItemId(itemId),
      sourceItemId: itemId,
      itemLineageId: itemId,
      ...commonVideo,
    });
  }
}

async function clearEditionItemLinks(editionId: string, publishedEditionIdValue: string) {
  const editionItems = await listSeedModelByIndex("EditionItem", "listEditionItemsByEditionAndSortKey", { editionId });
  const publishedEditionItems = await listSeedModelByIndex(
    "PublishedEditionItem",
    "listPublishedEditionItemsByEditionAndSortKey",
    { publishedEditionId: publishedEditionIdValue },
  );
  await Promise.all([
    ...editionItems.map((item) => deleteSeedModelRecord("EditionItem", String(item.id))),
    ...publishedEditionItems.map((item) => deleteSeedModelRecord("PublishedEditionItem", String(item.id))),
  ]);
}

async function clearArticleMediaAssets(itemId: string, publishedItemIdValue: string) {
  const mediaAssets = await listSeedModelByIndex("MediaAsset", "listMediaAssetsByItemAndSortKey", { itemId });
  const publishedMediaAssets = await listSeedModelByIndex(
    "PublishedMediaAsset",
    "listPublishedMediaAssetsByItemAndSortKey",
    { publishedItemId: publishedItemIdValue },
  );
  await Promise.all([
    ...publishedMediaAssets.map((asset) => deleteSeedModelRecord("PublishedMediaAsset", String(asset.id))),
    ...mediaAssets.map((asset) => deleteSeedModelRecord("MediaAsset", String(asset.id))),
  ]);
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

async function uploadSeedImage(article: Article, asset: ArticleImageAsset, index: number) {
  if (!asset.src) {
    return {
      storagePath: "",
      width: asset.layout ? Math.round(asset.layout.aspectRatio * asset.layout.preferredHeight) : undefined,
      height: asset.layout?.preferredHeight,
      themeVariants: undefined,
    };
  }

  const extension = guessImageExtension(asset.src);
  const storagePath = `media/articles/${article.slug}/${String(index + 1).padStart(2, "0")}-${asset.id}.${extension}`;
  const localFilepath = resolveLocalSeedFilepath(asset.src);
  if (localFilepath && (await storageObjectMatchesLocal(storagePath, localFilepath))) {
    console.log(`seed\timage-skip\t${storagePath}`);
  } else {
    const payload = await loadImagePayload(asset.src);
    console.log(`seed\timage-upload\t${storagePath}`);
    await uploadData({
      path: storagePath,
      data: payload.data,
      options: {
        contentType: payload.contentType,
        cacheControl: "public, max-age=31536000, immutable",
      },
    }).result;
  }

  const themeVariants: UploadedImageThemeVariants = {};
  if (asset.themeVariants?.dark?.src) {
    themeVariants.dark = {
      storagePath: await uploadSeedImageVariant(article, asset, index, "dark", asset.themeVariants.dark.src),
    };
  }

  return {
    storagePath,
    width: asset.layout ? Math.round(asset.layout.aspectRatio * asset.layout.preferredHeight) : undefined,
    height: asset.layout?.preferredHeight,
    themeVariants: Object.keys(themeVariants).length ? themeVariants : undefined,
  };
}

function getSeedArticleImageAssets(article: Article): ArticleImageAsset[] {
  const imageAssets = article.assets?.filter((asset) => asset.type === "image") ?? [];
  if (imageAssets.length > 0) return imageAssets;
  if (!article.image) return [];
  return [
    {
      ...article.image,
      src: article.image.src ?? "",
      id: `${article.slug}-primary-image`,
      type: "image",
      roles: ["lead", "continuation", "continuationInset"],
    },
  ];
}

function getSeedArticleVideoAsset(article: Article): ArticleVideoAsset | undefined {
  return article.video;
}

function shouldSeedVideoUploads(): boolean {
  return process.env.PAPYRUS_SEED_VIDEOS === "1";
}

/**
 * Resolves a seed asset `src` to a local filesystem path, or null when the src
 * is a remote URL (which we cannot cheaply HEAD-compare via Amplify Storage).
 */
function resolveLocalSeedFilepath(src: string): string | null {
  if (/^https?:\/\//.test(src)) return null;
  if (path.isAbsolute(src) && fs.existsSync(src)) return src;
  return path.join(process.cwd(), src.startsWith("/") ? path.join("public", src.slice(1)) : src);
}

/**
 * Returns true when the S3 object at `storagePath` already has the same bytes as
 * the local file at `filepath`, so the seed can skip re-uploading it. Uses a
 * cheap HEAD (getProperties) for size + ETag; only reads the local file to
 * compute an MD5 when the sizes already match. For single-part PUTs (all seed
 * media are well under the 5 MB multipart threshold) the S3 ETag is the object's
 * MD5, so a size + ETag match is a reliable identity check with no data transfer.
 * On any error or missing object, returns false so the caller uploads.
 */
async function storageObjectMatchesLocal(storagePath: string, filepath: string): Promise<boolean> {
  let props;
  try {
    props = await getProperties({ path: storagePath });
  } catch {
    return false;
  }
  const localSize = fs.statSync(filepath).size;
  const remoteSize = (props as { size?: number }).size;
  if (remoteSize !== localSize) return false;
  const localMd5 = createHash("md5").update(fs.readFileSync(filepath)).digest("hex");
  const etag = String((props as { eTag?: string }).eTag ?? "").replace(/^"|"$/g, "");
  return etag === localMd5;
}

type UploadedVideoThemeVariants = {
  light?: { storagePath: string };
  dark?: { storagePath: string };
};

async function buildSeedEditionVideoMetadata(
  editionSlug: string,
  asset: ArticleVideoAsset,
): Promise<Record<string, unknown>> {
  const baseRecord: Record<string, unknown> = { ...asset };
  if (!shouldSeedVideoUploads()) return baseRecord;
  const uploaded = await uploadSeedEditionVideo(editionSlug, asset);
  baseRecord.storagePath = uploaded.storagePath;
  const themeVariants = buildVideoThemeVariantsMetadata(asset.themeVariants, uploaded.themeVariants);
  if (themeVariants) baseRecord.themeVariants = themeVariants;
  return baseRecord;
}

async function uploadSeedEditionVideo(
  editionSlug: string,
  asset: ArticleVideoAsset,
): Promise<{ storagePath: string; themeVariants?: UploadedVideoThemeVariants }> {
  const storagePath = `media/editions/${editionSlug}/edition-overview.mp4`;
  await uploadSeedVideoFile(storagePath, asset.src);
  const themeVariants: UploadedVideoThemeVariants = {};
  const lightSrc = asset.themeVariants?.light?.src;
  if (lightSrc) {
    themeVariants.light = {
      storagePath: await uploadSeedVideoFile(
        `media/editions/${editionSlug}/edition-overview-light.mp4`,
        lightSrc,
      ),
    };
  }
  const darkSrc = asset.themeVariants?.dark?.src;
  if (darkSrc) {
    themeVariants.dark = {
      storagePath: await uploadSeedVideoFile(
        `media/editions/${editionSlug}/edition-overview-dark.mp4`,
        darkSrc,
      ),
    };
  }
  return {
    storagePath,
    themeVariants: Object.keys(themeVariants).length ? themeVariants : undefined,
  };
}

async function uploadSeedVideo(
  article: Article,
  asset: ArticleVideoAsset,
): Promise<{ storagePath: string; themeVariants?: UploadedVideoThemeVariants }> {
  const storagePath = `media/articles/${article.slug}/video-${article.slug}.mp4`;
  await uploadSeedVideoFile(storagePath, asset.src);
  const themeVariants: UploadedVideoThemeVariants = {};
  const lightSrc = asset.themeVariants?.light?.src;
  if (lightSrc) {
    themeVariants.light = {
      storagePath: await uploadSeedVideoFile(
        `media/articles/${article.slug}/video-${article.slug}-light.mp4`,
        lightSrc,
      ),
    };
  }
  const darkSrc = asset.themeVariants?.dark?.src;
  if (darkSrc) {
    themeVariants.dark = {
      storagePath: await uploadSeedVideoFile(
        `media/articles/${article.slug}/video-${article.slug}-dark.mp4`,
        darkSrc,
      ),
    };
  }
  return {
    storagePath,
    themeVariants: Object.keys(themeVariants).length ? themeVariants : undefined,
  };
}

async function uploadSeedVideoFile(storagePath: string, assetSrc: string): Promise<string> {
  const localFilepath = resolveLocalSeedFilepath(assetSrc);
  if (localFilepath && (await storageObjectMatchesLocal(storagePath, localFilepath))) {
    console.log(`seed\tvideo-skip\t${storagePath}`);
    return storagePath;
  }
  const payload = await loadVideoPayload(assetSrc);
  console.log(`seed\tvideo-upload\t${storagePath}`);
  await uploadData({
    path: storagePath,
    data: payload.data,
    options: {
      contentType: payload.contentType,
      cacheControl: "public, max-age=31536000, immutable",
    },
  }).result;

  return storagePath;
}

async function loadVideoPayload(src: string): Promise<{ data: Uint8Array; contentType: string }> {
  const filepath =
    path.isAbsolute(src) && fs.existsSync(src)
      ? src
      : path.join(process.cwd(), src.startsWith("/") ? path.join("public", src.slice(1)) : src);
  if (!fs.existsSync(filepath)) {
    throw new Error(`Seed video file not found: ${filepath}. Run 'poetry run papyrus videos seed' first.`);
  }
  return {
    data: fs.readFileSync(filepath),
    contentType: "video/mp4",
  };
}

function getVideoMediaMetadata(
  asset: ArticleVideoAsset,
  uploadedThemeVariants?: UploadedVideoThemeVariants,
): Record<string, unknown> {
  const themeVariants = buildVideoThemeVariantsMetadata(asset.themeVariants, uploadedThemeVariants);
  return {
    sourceUrl: asset.src,
    ...(asset.posterSrc ? { posterSrc: asset.posterSrc } : {}),
    ...(asset.durationSeconds ? { durationSeconds: asset.durationSeconds } : {}),
    ...(themeVariants ? { themeVariants } : {}),
  };
}

function buildVideoThemeVariantsMetadata(
  seedVariants: ArticleVideoAsset["themeVariants"],
  uploadedThemeVariants?: UploadedVideoThemeVariants,
): Record<string, unknown> | undefined {
  const lightSrc = seedVariants?.light?.src;
  const darkSrc = seedVariants?.dark?.src;
  const lightStoragePath = uploadedThemeVariants?.light?.storagePath;
  const darkStoragePath = uploadedThemeVariants?.dark?.storagePath;
  if (!lightSrc && !darkSrc && !lightStoragePath && !darkStoragePath) return undefined;
  return {
    ...(lightSrc || lightStoragePath
      ? {
          light: {
            ...(lightStoragePath ? { storagePath: lightStoragePath } : {}),
            ...(lightSrc ? { sourceUrl: lightSrc } : {}),
          },
        }
      : {}),
    ...(darkSrc || darkStoragePath
      ? {
          dark: {
            ...(darkStoragePath ? { storagePath: darkStoragePath } : {}),
            ...(darkSrc ? { sourceUrl: darkSrc } : {}),
          },
        }
      : {}),
  };
}

async function uploadSeedImageVariant(
  article: Article,
  asset: ArticleImageAsset,
  index: number,
  variant: "dark",
  src: string,
): Promise<string> {
  const extension = guessImageExtension(src);
  const storagePath = `media/articles/${article.slug}/${String(index + 1).padStart(2, "0")}-${asset.id}-${variant}.${extension}`;
  const localFilepath = resolveLocalSeedFilepath(src);
  if (localFilepath && (await storageObjectMatchesLocal(storagePath, localFilepath))) {
    console.log(`seed\timage-skip\t${storagePath}`);
    return storagePath;
  }
  const payload = await loadImagePayload(src);
  console.log(`seed\timage-upload\t${storagePath}`);
  await uploadData({
    path: storagePath,
    data: payload.data,
    options: {
      contentType: payload.contentType,
      cacheControl: "public, max-age=31536000, immutable",
    },
  }).result;
  return storagePath;
}

async function loadImagePayload(src: string): Promise<{ data: Uint8Array; contentType: string }> {
  if (/^https?:\/\//.test(src)) {
    const response = await fetch(src);
    if (!response.ok) throw new Error(`Could not fetch image ${src}: ${response.status} ${response.statusText}`);
    return {
      data: new Uint8Array(await response.arrayBuffer()),
      contentType: response.headers.get("content-type") ?? "image/jpeg",
    };
  }

  const filepath =
    path.isAbsolute(src) && fs.existsSync(src)
      ? src
      : path.join(process.cwd(), src.startsWith("/") ? path.join("public", src.slice(1)) : src);
  return {
    data: fs.readFileSync(filepath),
    contentType: getContentTypeFromFilename(filepath),
  };
}

type SeedAttachmentRecord = {
  id: string;
  ownerKind: string;
  ownerId: string;
  ownerLineageId: string;
  ownerVersionNumber: number | null;
  ownerVersionKey: string | null;
  role: string;
  sortKey: string;
  storagePath: string;
  filename: string;
  mediaType: string;
  byteSize: number;
  sha256: string;
  etag: null;
  importRunId: string | null;
  createdAt: string;
  updatedAt: string;
  status: string;
};

type SeedAttachmentUploadSlot = {
  uploadId: string;
  uploadUrl: string;
  method?: string | null;
  requiredHeaders?: Record<string, string> | string | null;
};

function normalizeArticleBodyText(body: string[]): string {
  return body.map((part) => String(part ?? "").trim()).filter(Boolean).join("\n\n");
}

function normalizeOptionalText(value: unknown): string | null {
  const normalized = String(value ?? "").trim();
  return normalized || null;
}

function contentAttachmentEditorialRecord(
  bodyAttachment: SeedAttachmentRecord | null,
  excerptAttachment: SeedAttachmentRecord | null,
): Record<string, unknown> {
  const contentAttachments: Record<string, unknown> = {};
  if (bodyAttachment) {
    contentAttachments.body = {
      role: bodyAttachment.role,
      storagePath: bodyAttachment.storagePath,
      mediaType: bodyAttachment.mediaType,
      filename: bodyAttachment.filename,
      byteSize: bodyAttachment.byteSize,
      ownerKind: bodyAttachment.ownerKind,
    };
  }
  if (excerptAttachment) {
    contentAttachments.excerpt = {
      role: excerptAttachment.role,
      storagePath: excerptAttachment.storagePath,
      mediaType: excerptAttachment.mediaType,
      filename: excerptAttachment.filename,
      byteSize: excerptAttachment.byteSize,
      ownerKind: excerptAttachment.ownerKind,
    };
  }
  return { contentAttachments };
}

async function upsertSeedTextAttachment(input: {
  ownerKind: string;
  ownerId: string;
  ownerLineageId: string;
  ownerVersionNumber: number | null;
  ownerVersionKey: string | null;
  role: string;
  sortKey: string;
  filename: string;
  mediaType: string;
  content: string;
  now: string;
  importRunId: string | null;
}): Promise<SeedAttachmentRecord> {
  const body = Buffer.from(input.content.endsWith("\n") ? input.content : `${input.content}\n`, "utf8");
  const attachmentVariables = {
    ownerKind: input.ownerKind,
    ownerId: input.ownerId,
    ownerLineageId: input.ownerLineageId,
    ownerVersionNumber: input.ownerVersionNumber,
    ownerVersionKey: input.ownerVersionKey,
    role: input.role,
    sortKey: input.sortKey,
    filename: input.filename,
    mediaType: input.mediaType,
    byteSize: body.byteLength,
    sha256: createHash("sha256").update(body).digest("hex"),
    importRunId: input.importRunId,
    status: "active",
  };
  const client = getSeedClient() as unknown as GraphQLClient;
  const slotResponse = await client.graphql({
    query: CREATE_MODEL_ATTACHMENT_UPLOAD_MUTATION,
    variables: attachmentVariables,
    authMode: "userPool",
  });
  assertNoGraphQLErrors(slotResponse.errors);
  const slot = slotResponse.data?.createModelAttachmentUpload as SeedAttachmentUploadSlot | null | undefined;
  if (!slot?.uploadUrl) throw new Error("Seed attachment upload slot did not include an upload URL.");
  const uploadResponse = await fetch(slot.uploadUrl, {
    method: slot.method ?? "PUT",
    headers: normalizeUploadHeaders(slot.requiredHeaders),
    body,
  });
  if (!uploadResponse.ok) {
    throw new Error(`Seed attachment upload failed: ${uploadResponse.status} ${uploadResponse.statusText}`);
  }
  const completeResponse = await client.graphql({
    query: COMPLETE_MODEL_ATTACHMENT_UPLOAD_MUTATION,
    variables: {
      uploadId: slot.uploadId,
      ...attachmentVariables,
    },
    authMode: "userPool",
  });
  assertNoGraphQLErrors(completeResponse.errors);
  const attachment = completeResponse.data?.completeModelAttachmentUpload as SeedAttachmentRecord | null | undefined;
  if (!attachment) throw new Error("Seed attachment upload completed without a ModelAttachment record.");
  return attachment;
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

function modelPayloadStoragePath(ownerKind: string, ownerId: string, role: string, filename: string): string {
  const rootPrefix = ownerKind === "publishedItem" ? "media/payloads" : "newsroom/payloads";
  return `${rootPrefix}/${safeId(ownerKind)}/${safeId(ownerId)}/${safeId(role)}/${filename}`;
}

function normalizeUploadHeaders(headers: Record<string, string> | string | null | undefined): Record<string, string> {
  if (!headers) return {};
  if (typeof headers === "string") {
    try {
      const parsed = JSON.parse(headers) as Record<string, unknown>;
      return Object.fromEntries(
        Object.entries(parsed).map(([key, value]) => [String(key), String(value)]),
      );
    } catch {
      return {};
    }
  }
  return Object.fromEntries(
    Object.entries(headers).map(([key, value]) => [String(key), String(value)]),
  );
}

function modelAttachmentId(ownerKind: string, ownerId: string, role: string, sortKey: string): string {
  return `model-attachment-${safeId(ownerKind)}-${safeId(ownerId)}-${safeId(role)}-${safeId(sortKey)}`;
}

function safeId(value: unknown): string {
  const raw = String(value ?? "payload").trim();
  const normalized = raw
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "payload";
  if (normalized.length <= 80) return normalized;
  const digest = createHash("sha256").update(raw).digest("hex").slice(0, 12);
  return `${normalized.slice(0, 67).replace(/-+$/g, "")}-${digest}`;
}

async function listSeedModelByIndex(
  modelName: keyof DataClient["models"],
  queryName: string,
  input: Record<string, unknown>,
): Promise<Array<Record<string, unknown>>> {
  const model = (getSeedClient().models as Record<string, unknown>)[String(modelName)] as Record<string, unknown>;
  const query = model[queryName] as (
    input: Record<string, unknown>,
    options: { authMode: "userPool"; nextToken?: string | null },
  ) => Promise<{ data?: Array<Record<string, unknown> | null> | null; errors?: unknown[]; nextToken?: string | null }>;
  const items: Array<Record<string, unknown>> = [];
  let nextToken: string | null | undefined;
  do {
    const response = await query(input, { authMode: "userPool", nextToken });
    assertNoGraphQLErrors(response.errors);
    items.push(...(response.data ?? []).filter((item): item is Record<string, unknown> => item !== null));
    nextToken = response.nextToken;
  } while (nextToken);
  return items;
}

async function deleteSeedModelRecord(modelName: keyof DataClient["models"], id: string) {
  const model = (getSeedClient().models as Record<string, unknown>)[String(modelName)] as {
    delete(input: { id: string }, options: { authMode: "userPool" }): Promise<{ errors?: unknown[] }>;
  };
  const response = await model.delete({ id }, { authMode: "userPool" });
  assertNoGraphQLErrors(response.errors);
}

function orderArticles(source: Article[], articleOrder: string[]): Article[] {
  return [...source].sort((left, right) => {
    const leftIndex = articleOrder.indexOf(left.slug);
    const rightIndex = articleOrder.indexOf(right.slug);
    const leftRank = leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex;
    const rightRank = rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex;
    return leftRank - rightRank || left.slug.localeCompare(right.slug);
  });
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function getImageExtension(contentType: string, src: string): string {
  if (contentType.includes("png")) return "png";
  if (contentType.includes("svg")) return "svg";
  if (contentType.includes("webp")) return "webp";
  if (contentType.includes("gif")) return "gif";

  const match = new URL(src, "file:///").pathname.match(/\.([a-z0-9]+)$/i);
  return match?.[1] ?? "jpg";
}

/**
 * Derives the storage extension for an image src without loading the file, so
 * the storage path can be computed for a pre-upload identity check. Local files
 * use the filename content type; remote URLs fall back to the URL's extension.
 */
function guessImageExtension(src: string): string {
  const local = resolveLocalSeedFilepath(src);
  if (local) return getImageExtension(getContentTypeFromFilename(local), src);
  return getImageExtension("", src);
}

function getContentTypeFromFilename(filename: string): string {
  const extension = path.extname(filename).toLowerCase();
  if (extension === ".png") return "image/png";
  if (extension === ".svg") return "image/svg+xml";
  if (extension === ".webp") return "image/webp";
  if (extension === ".gif") return "image/gif";
  return "image/jpeg";
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

function getMediaMetadata(asset: ArticleImageAsset, uploadedThemeVariants?: UploadedImageThemeVariants): Record<string, unknown> {
  const themeVariants =
    asset.themeVariants?.dark?.src || uploadedThemeVariants?.dark?.storagePath
      ? {
          dark: {
            ...(asset.themeVariants?.dark?.src ? { sourceUrl: asset.themeVariants.dark.src } : {}),
            ...(uploadedThemeVariants?.dark?.storagePath ? { storagePath: uploadedThemeVariants.dark.storagePath } : {}),
          },
        }
      : undefined;
  return {
    ...(asset.src ? { sourceUrl: asset.src } : {}),
    ...(asset.layout?.inlineFloat ? { inlineFloat: asset.layout.inlineFloat } : {}),
    ...(themeVariants ? { themeVariants } : {}),
  };
}

function withVersionFields<T extends Record<string, unknown>>(
  record: T,
  options: {
    lineageId: string;
    versionCreatedAt: string;
    versionCreatedBy: string;
    changeReason: string;
  },
): T & {
  lineageId: string;
  versionNumber: number;
  previousVersionId: null;
  versionState: string;
  versionCreatedAt: string;
  versionCreatedBy: string;
  changeReason: string;
  contentHash: string;
} {
  const versioned = {
    ...record,
    lineageId: options.lineageId,
    versionNumber: 1,
    previousVersionId: null,
    versionState: "current",
    versionCreatedAt: options.versionCreatedAt,
    versionCreatedBy: options.versionCreatedBy,
    changeReason: options.changeReason,
  };
  return {
    ...versioned,
    contentHash: contentHashFor(versioned),
  };
}

function contentHashFor(value: unknown): string {
  return `sha256:${createHash("sha256").update(stableStringify(value)).digest("hex")}`;
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, entry]) => entry !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return `{${entries.map(([key, entry]) => `${JSON.stringify(key)}:${stableStringify(entry)}`).join(",")}}`;
}

function publishedEditionId(editionId: string): string {
  return `published-${editionId}`;
}

function publishedItemId(itemId: string): string {
  return `published-${itemId}`;
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
