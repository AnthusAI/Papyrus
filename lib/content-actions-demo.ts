import { ContentActionFailure } from "./content-actions-client";
import type {
  DeriveMarkusInput,
  DeriveMarkusResult,
  PublishItemResult,
  SaveItemDraftInput,
  SaveItemDraftResult,
  UnpublishItemResult,
} from "./content-actions-client";
import {
  createDemoArticleRecords,
  demoContentHash,
  type DemoArticleRecord,
} from "./newsroom-demo-articles";
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

  const requireRecord = (id: string): DemoArticleRecord => {
    const record = records.get(id);
    if (!record) throw new ContentActionFailure([{ code: "not-found", message: "That article was not found.", line: null }]);
    return record;
  };

  return {
    actions: {
      async deriveMarkus(input: DeriveMarkusInput): Promise<DeriveMarkusResult> {
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
        if (existing && input.expectedContentHash !== null && input.expectedContentHash !== existing.contentHash) {
          throw new ContentActionFailure([
            { code: "conflict", message: "The item changed since it was loaded.", line: null },
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
        const changed = record.status !== "published" || record.publishedContentHash !== record.contentHash;
        const versionNumber = changed ? (record.versionNumber ?? 0) + 1 : record.versionNumber;
        records.set(id, {
          ...record,
          status: "published",
          everPublished: true,
          publishedContentHash: record.contentHash,
          versionNumber,
          updatedAt: new Date().toISOString(),
        });
        return { ok: true, changed, publishedId: `published-${id}`, versionNumber };
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
      const record = requireRecord(id);
      return {
        id: record.id,
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
      };
    },
  };
}
