export type DemoArticleRecord = {
  id: string;
  type: string;
  slug: string;
  section: string | null;
  title: string;
  status: "draft" | "published";
  frontMatterYaml: string;
  bodyMarkus: string;
  contentHash: string;
  publishedContentHash: string | null;
  versionNumber: number | null;
  everPublished: boolean;
  updatedAt: string;
};

export function demoContentHash(frontMatterYaml: string, bodyMarkus: string): string {
  let hash = 5381;
  const text = `${frontMatterYaml}\u0000${bodyMarkus}`;
  for (let index = 0; index < text.length; index += 1) {
    hash = ((hash << 5) + hash + text.charCodeAt(index)) >>> 0;
  }
  return `demo:${hash.toString(16)}`;
}

function demoRecord(
  fields: Pick<DemoArticleRecord, "id" | "slug" | "section" | "title" | "bodyMarkus" | "updatedAt"> & {
    type?: string;
    status: "draft" | "published";
    publishedBody?: string;
    versionNumber: number | null;
  },
): DemoArticleRecord {
  const frontMatterYaml = `title: ${fields.title}\n`;
  const contentHash = demoContentHash(frontMatterYaml, fields.bodyMarkus);
  const publishedContentHash = fields.status === "published"
    ? demoContentHash(frontMatterYaml, fields.publishedBody ?? fields.bodyMarkus)
    : null;
  return {
    id: fields.id,
    type: fields.type ?? "article",
    slug: fields.slug,
    section: fields.section,
    title: fields.title,
    status: fields.status,
    frontMatterYaml,
    bodyMarkus: fields.bodyMarkus,
    contentHash,
    publishedContentHash,
    versionNumber: fields.versionNumber,
    everPublished: fields.status === "published",
    updatedAt: fields.updatedAt,
  };
}

export function createDemoArticleRecords(): DemoArticleRecord[] {
  return [
    demoRecord({
      id: "demo-article-changed",
      slug: "forty-billion-dollars",
      section: "business",
      title: "Forty Billion Dollars",
      bodyMarkus: "The raise doubled again this quarter.\n\nAnalysts expect the pace to slow.\n",
      publishedBody: "The raise doubled this quarter.\n",
      status: "published",
      versionNumber: 2,
      updatedAt: "2026-10-05T16:00:00.000Z",
    }),
    demoRecord({
      id: "demo-article-published",
      slug: "harbor-cranes-return",
      section: "local",
      title: "Harbor Cranes Return",
      bodyMarkus: "# Harbor Cranes Return\n\nThe cranes were lifted back into place on Monday.\n",
      status: "published",
      versionNumber: 1,
      updatedAt: "2026-10-04T12:00:00.000Z",
    }),
    demoRecord({
      id: "demo-article-draft",
      slug: "council-budget-notes",
      section: "politics",
      title: "Council Budget Notes",
      bodyMarkus: "Notes from the budget session.\n",
      status: "draft",
      versionNumber: null,
      updatedAt: "2026-10-03T09:00:00.000Z",
    }),
  ];
}
