import { ContentActionFailure } from "./content-actions-client";
import { typeForNewStory } from "./site-story-types";
import { isLocalPreviewEnabled } from "./local-preview";
import type {
  DeriveMarkusInput,
  DeriveMarkusResult,
  PublishItemResult,
  SaveItemDraftInput,
  SaveItemDraftResult,
  UnpublishItemResult,
  MoveStoryStageInput,
  MoveStoryStageResult,
  ScheduleStoryInput,
  ScheduleStoryResult,
  CreateStoryFromReferenceInput,
  CreateStoryFromReferenceResult,
} from "./content-actions-client";
import { SEEDED_FROM_KEY, SEEDED_IMAGE_KEY, seededImageLine, sourceAttribution, startBody } from "./story-from-reference";
import {
  createDemoArticleRecords,
  demoContentHash,
  type DemoArticleRecord,
} from "./newsroom-demo-articles";
import { createLocalPreviewEditableArticle, lineageForPreviewVersion, localPreviewScheduleFields, recordLocalPreviewDesk, recordLocalPreviewVersion, setLocalPreviewSchedule } from "./local-preview-seed";
import { scheduleFromFields } from "./story-schedule";
import { sourceLineOffset, type ArticlesBackend, type EditableArticle, type NewsroomArticleRow } from "./newsroom-articles";

function titleFromYaml(frontMatterYaml: string | null, fallback: string): string {
  for (const line of (frontMatterYaml ?? "").split("\n")) {
    const match = /^title\s*:\s*(.*)$/.exec(line);
    if (match && match[1].trim()) return match[1].trim().replace(/^["']|["']$/g, "");
  }
  return fallback;
}

const DEMO_IMAGE_DIRECTIVE = /^::image\{([^}]*)\}$/;

function demoAttribute(attributes: string, name: string): string {
  const match = new RegExp(`${name}="([^"]*)"`).exec(attributes);
  return match ? match[1] : "";
}

async function deriveThroughPreviewMarkusEngine(input: DeriveMarkusInput): Promise<DeriveMarkusResult | null> {
  try {
    const response = await fetch("/api/local-preview/derive", { method: "POST", body: JSON.stringify({ frontMatterYaml: input.frontMatterYaml, bodyMarkus: input.bodyMarkus }) });
    if (!response.ok) return null;
    const result = await response.json() as DeriveMarkusResult & { error?: string };
    if (result.error) return null;
    return input.includeIr ? result : { ...result, bodyIr: undefined };
  } catch {
    return null;
  }
}

function demoEnvelope(bodyMarkus: string) {
  const images: Record<string, Record<string, unknown>> = {};
  const children = bodyMarkus
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      const heading = /^(#{1,6})\s+(.*)$/.exec(block);
      if (heading) {
        return { type: "heading", level: heading[1].length, inline: [{ type: "text", text: heading[2] }], line: null };
      }
      const image = DEMO_IMAGE_DIRECTIVE.exec(block);
      if (image) {
        const token = `PAPYRUSMARKUP${String(Object.keys(images).length + 1).padStart(5, "0")}END`;
        images[token] = {
          src: demoAttribute(image[1], "src"),
          alt: demoAttribute(image[1], "alt"),
          layout: demoAttribute(image[1], "layout") || null,
        };
        return { type: "paragraph", inline: [{ type: "text", text: token }], line: null };
      }
      return { type: "paragraph", inline: [{ type: "text", text: block }], line: null };
    });
  return {
    schemaVersion: 1,
    markus: { version: "demo", irSchemaVersion: 1 },
    document: { type: "document", schema_version: 1, front_matter: {}, children },
    papyrus: { images, citations: {}, citationLists: {}, entries: {}, bibliography: [] },
  };
}

export function createDemoArticlesBackend(): ArticlesBackend {
  const records = new Map<string, DemoArticleRecord>(createDemoArticleRecords().map((record) => [record.id, record]));
  let created = 0;
  const storiesFromReference = new Map<string, string[]>();

  /** A local-preview Story is added to the demo records the first time something reads or changes it. */
  const loadPreviewRecord = (id: string): void => {
    if (records.has(id)) return;
    const previewRecord = createLocalPreviewEditableArticle(id);
    if (!previewRecord) return;
    records.set(id, {
      ...previewRecord,
      title: titleFromYaml(previewRecord.frontMatterYaml, previewRecord.slug),
      status: previewRecord.status === "published" ? "published" : "draft",
      contentHash: demoContentHash(previewRecord.frontMatterYaml, previewRecord.bodyMarkus),
      publishedContentHash: previewRecord.status === "published" ? demoContentHash(previewRecord.frontMatterYaml, previewRecord.bodyMarkus) : null,
      updatedAt: new Date().toISOString(),
    });
  };

  const requireRecord = (id: string): DemoArticleRecord => {
    const record = records.get(id);
    if (!record) throw new ContentActionFailure([{ code: "not-found", message: "That article was not found.", line: null }]);
    return record;
  };

  return {
    actions: {
      async deriveMarkus(input: DeriveMarkusInput): Promise<DeriveMarkusResult> {
        if (isLocalPreviewEnabled()) {
          const derived = await deriveThroughPreviewMarkusEngine(input);
          if (derived) return derived;
        }
        const lines = input.bodyMarkus.split("\n");
        const invalidIndex = lines.findIndex((line) => line.includes(":::nope"));
        if (invalidIndex >= 0) {
          throw new ContentActionFailure([
            { code: "markus-validation", message: 'Unknown directive "nope".', line: invalidIndex + 1 + sourceLineOffset(input.frontMatterYaml) },
          ]);
        }
        const envelope = demoEnvelope(input.bodyMarkus);
        return {
          ok: true,
          bodyIrBytes: JSON.stringify(envelope).length,
          ...(input.includeIr ? { bodyIr: envelope } : {}),
          errors: [],
        };
      },
      async saveItemDraft(input: SaveItemDraftInput): Promise<SaveItemDraftResult> {
        const existing = input.id ? requireRecord(input.id) : null;
        if (input.newVersion && existing) {
          const lineageId = createLocalPreviewEditableArticle(existing.id)?.lineageId ?? existing.id;
          const versionNumber = (existing.versionNumber ?? 1) + 1;
          const id = `${lineageId}-v${versionNumber}`;
          const frontMatterYaml = input.frontMatterYaml ?? "";
          const record: DemoArticleRecord = {
            ...existing,
            id,
            type: input.type,
            publishedType: existing.publishedType ?? (existing.everPublished ? existing.type : null),
            slug: existing.slug,
            section: input.section,
            title: titleFromYaml(input.frontMatterYaml, existing.slug),
            status: "draft",
            frontMatterYaml,
            bodyMarkus: input.bodyMarkus,
            contentHash: demoContentHash(frontMatterYaml, input.bodyMarkus),
            versionNumber,
            updatedAt: new Date().toISOString(),
          };
          records.set(id, record);
          recordLocalPreviewVersion(lineageId, { id, versionNumber, versionState: "current", status: "draft", stage: null, headline: record.title, changeReason: input.changeReason ?? null, versionCreatedBy: "You", versionCreatedAt: record.updatedAt, updatedAt: record.updatedAt });
          return { ok: true, item: { id, contentHash: record.contentHash, status: "draft", slug: record.slug, versionNumber } };
        }
        if (existing && input.expectedContentHash !== null && input.expectedContentHash !== existing.contentHash) {
          throw new ContentActionFailure([
            { code: "conflict", message: "The item changed since it was loaded.", line: null },
          ]);
        }
        if (existing && existing.status === "published" && existing.type !== input.type) {
          throw new ContentActionFailure([
            { code: "type-locked", message: `This story is live as the type ${existing.type}. Save it as a new version to change its type: the live address moves only when that version is published.`, line: null },
          ]);
        }
        if (existing && existing.everPublished && existing.slug !== input.slug) {
          throw new ContentActionFailure([
            { code: "slug-locked", message: "The slug cannot change once the item has been published.", line: null },
          ]);
        }
        const id = existing?.id ?? `demo-article-new-${(created += 1)}`;
        const title = titleFromYaml(input.frontMatterYaml, input.slug);
        const frontMatterYaml = input.frontMatterYaml ?? "";
        const record: DemoArticleRecord = {
          id,
          type: input.type,
          slug: input.slug,
          section: input.section,
          title,
          status: existing?.status ?? "draft",
          frontMatterYaml,
          bodyMarkus: input.bodyMarkus,
          contentHash: demoContentHash(frontMatterYaml, input.bodyMarkus),
          publishedContentHash: existing?.publishedContentHash ?? null,
          versionNumber: existing?.versionNumber ?? null,
          everPublished: existing?.everPublished ?? false,
          updatedAt: new Date().toISOString(),
        };
        records.set(id, record);
        recordLocalPreviewDesk(id, record.section);
        return {
          ok: true,
          item: {
            id,
            contentHash: record.contentHash,
            status: record.status,
            slug: record.slug,
            versionNumber: record.versionNumber,
          },
        };
      },
      async publishItem(id: string): Promise<PublishItemResult> {
        const record = requireRecord(id);
        if (record.type === "untyped") {
          throw new ContentActionFailure([{ code: "type-required", message: "This story has no type yet. Choose its type, then publish: the site decides where a page lives from it.", line: null }]);
        }
        const changed = record.status !== "published" || record.publishedContentHash !== record.contentHash;
        const publishedLineage = createLocalPreviewEditableArticle(id)?.lineageId ?? lineageForPreviewVersion(id);
        if (publishedLineage) setLocalPreviewSchedule(publishedLineage, null);   // publishing now ends the schedule
        const versionNumber = changed ? (record.versionNumber ?? 0) + 1 : record.versionNumber;
        const typeChangedFrom = changed && record.publishedType && record.publishedType !== record.type ? record.publishedType : undefined;
        records.set(id, {
          ...record,
          status: "published",
          publishedType: null,
          everPublished: true,
          publishedContentHash: record.contentHash,
          versionNumber,
          updatedAt: new Date().toISOString(),
        });
        return { ok: true, changed, publishedId: `published-${id}`, versionNumber, ...(typeChangedFrom ? { typeChangedFrom } : {}) };
      },
      async setItemStars(itemId: string, stars: number | null): Promise<void> {
        // A plain update of the record: no new version, and a published Story stays as published as it was.
        loadPreviewRecord(itemId);
        records.set(itemId, { ...requireRecord(itemId), starRating: stars });
      },
      async scheduleStory(input: ScheduleStoryInput): Promise<ScheduleStoryResult> {
        try {
          const fields = setLocalPreviewSchedule(input.lineageId, input.scheduledPublishAt);
          return { ok: true, scheduledPublishAt: fields.scheduledPublishAt ?? null, scheduleState: fields.scheduleState ?? null, scheduledBy: fields.scheduledBy ?? null, scheduledAt: fields.scheduledAt ?? null };
        } catch (error) {
          throw new ContentActionFailure([{ code: "schedule-refused", message: error instanceof Error ? error.message : String(error), line: null }]);
        }
      },
      async moveStoryStage(input: MoveStoryStageInput): Promise<MoveStoryStageResult> {
        return { ok: true, changed: true, stage: input.stage };
      },
      async createStoryFromReference(input: CreateStoryFromReferenceInput): Promise<CreateStoryFromReferenceResult> {
        // The preview has no backend to look the Reference up in, so it is given the same facts the real action reads.
        const hint = input.preview;
        if (!hint) throw new ContentActionFailure([{ code: "story-not-created", message: "The preview was not given the Reference.", line: null }]);
        const already = storiesFromReference.get(input.referenceId) ?? [];
        if (already.length && !input.again) {
          return { ok: true, created: false, referenceLineageId: input.referenceId, existing: already.map((id) => ({ itemId: id, lineageId: id, title: records.get(id)?.title ?? hint.title, stage: "copywriting" })) };
        }
        const site = hint.site ?? (hint.url ? new URL(hint.url).hostname.replace(/^www\./, "") : null);
        const image = hint.imageUrl ? `${seededImageLine(hint.imageUrl, hint.title, hint.site)}\n\n` : "";
        const bodyMarkus = image + startBody(hint.summary, sourceAttribution(hint.title, hint.url, site));
        const summaryState = hint.summary?.trim() ? "included" : "none";
        const frontMatterYaml = [
          `title: ${JSON.stringify(hint.title)}`,
          `${SEEDED_FROM_KEY}:\n  kind: reference\n  referenceLineageId: ${JSON.stringify(input.referenceId)}\n  summary: ${summaryState}`,
          ...(hint.imageUrl ? [`${SEEDED_IMAGE_KEY}:\n  url: ${JSON.stringify(hint.imageUrl)}\n  hosted: false${hint.site ? `\n  credit: ${JSON.stringify(`Image: ${hint.site}`)}` : ""}`] : []),
        ].join("\n") + "\n";
        const id = `demo-article-new-${(created += 1)}`;
        records.set(id, {
          id, type: input.itemType ?? typeForNewStory(), slug: `from-reference-${created}`, section: null, title: hint.title, status: "draft", frontMatterYaml, bodyMarkus,
          contentHash: demoContentHash(frontMatterYaml, bodyMarkus), publishedContentHash: null, versionNumber: null, everPublished: false, updatedAt: new Date().toISOString(),
        });
        storiesFromReference.set(input.referenceId, [...already, id]);
        return { ok: true, created: true, itemId: id, lineageId: id, title: hint.title, itemType: input.itemType ?? typeForNewStory(), stage: "copywriting", summary: summaryState, image: hint.imageUrl ? "seeded" : "none", imageCredit: hint.imageUrl && hint.site ? `Image: ${hint.site}` : null };
      },
      async unpublishItem(id: string): Promise<UnpublishItemResult> {
        const record = requireRecord(id);
        const changed = record.status === "published";
        records.set(id, {
          ...record,
          status: "draft",
          publishedContentHash: null,
          updatedAt: new Date().toISOString(),
        });
        return { ok: true, changed };
      },
    },
    async listRows(): Promise<NewsroomArticleRow[]> {
      return [...records.values()]
        .map((record) => ({
          id: record.id,
          type: record.type,
          slug: record.slug,
          section: record.section,
          title: record.title || record.slug,
          status: record.status,
          pending: record.status === "published" && record.publishedContentHash !== record.contentHash,
          updatedAt: record.updatedAt,
        }))
        .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
    },
    async loadArticle(id: string): Promise<EditableArticle> {
      loadPreviewRecord(id);
      const record = requireRecord(id);
      return {
        id: record.id,
        lineageId: createLocalPreviewEditableArticle(record.id)?.lineageId ?? lineageForPreviewVersion(record.id),
        type: record.type,
        section: record.section,
        slug: record.slug,
        frontMatterYaml: record.frontMatterYaml,
        bodyMarkus: record.bodyMarkus,
        contentHash: record.contentHash,
        status: record.status,
        versionNumber: record.versionNumber,
        aliases: [],
        everPublished: record.everPublished,
        publishedType: record.publishedType ?? (record.everPublished ? record.type : null),
        starRating: record.starRating ?? null,
        schedule: scheduleFromFields(localPreviewScheduleFields(createLocalPreviewEditableArticle(record.id)?.lineageId ?? lineageForPreviewVersion(record.id) ?? record.id)),
      };
    },
  };
}
