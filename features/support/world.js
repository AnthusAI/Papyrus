const { After, Before, setDefaultTimeout, setWorldConstructor } = require("@cucumber/cucumber");
const { chromium } = require("playwright");
const {
  buildCapabilities,
  getEffectivePresentation,
  readCapabilitiesFromDocument,
  requireCapability,
  shouldSkipScenario,
} = require("./capabilities");

setDefaultTimeout(60_000);

let cachedSiteCapabilities = null;

class PapyrusWorld {
  constructor() {
    this.baseUrl = process.env.PAPYRUS_BASE_URL ?? "http://127.0.0.1:3001";
    this.browser = null;
    this.page = null;
    this.consoleErrors = [];
    this.currentScenarioId = null;
    this.testEditorReader = false;
    this.newsroomSummaryDelayMs = 0;
    this.newsroomSummaryMock = null;
    this.newsroomMessageDetailMock = null;
    this.newsroomReferenceSummaryPayloadMock = null;
    this.newsroomReferenceExtractedTextMock = null;
    this.newsroomQualityMutationMock = null;
    this.capabilities = null;
    this.pendingReaderSettings = null;
  }

  async probeSiteCapabilities() {
    if (cachedSiteCapabilities) {
      this.capabilities = cachedSiteCapabilities;
      return this.capabilities;
    }

    const browser = await chromium.launch({
      headless: process.env.PAPYRUS_HEADLESS !== "false",
    });
    const page = await browser.newPage();
    await page.goto(this.baseUrl, { waitUntil: "domcontentloaded" });
    const raw = await page.evaluate(readCapabilitiesFromDocument);
    cachedSiteCapabilities = buildCapabilities(raw);
    this.capabilities = cachedSiteCapabilities;
    await browser.close();
    return this.capabilities;
  }

  async readCapabilitiesFromActivePage() {
    if (!this.page) return;
    const raw = await this.page.evaluate(readCapabilitiesFromDocument);
    this.capabilities = buildCapabilities(raw);
    cachedSiteCapabilities = this.capabilities;
  }

  requireCapability(capability) {
    requireCapability(this, capability);
  }

  getEffectivePresentation() {
    return getEffectivePresentation(this);
  }

  async openScenario(scenarioId, width, height) {
    await this.openEditionScenario(scenarioId, width, height);
  }

  async openNewspaperScenario(scenarioId, width, height) {
    this.currentScenarioId = scenarioId;
    await this.openPath(`/?scenario=${encodeURIComponent(scenarioId)}`, width, height);
    await this.page.waitForFunction(
      (expectedScenarioId) => (
        window.__PAPYRUS_LAYOUT__ &&
        window.__PAPYRUS_SCENARIO__ === expectedScenarioId &&
        document.querySelector(".paper-page--active")
      ),
      scenarioId,
      { timeout: 15_000 },
    );
  }

  async openEditionScenario(scenarioId, width, height) {
    this.currentScenarioId = scenarioId;
    await this.openPath(`/?scenario=${encodeURIComponent(scenarioId)}`, width, height);
    await this.page.waitForFunction(
      (expectedScenarioId) => (
        window.__PAPYRUS_SCENARIO__ === expectedScenarioId &&
        (document.querySelector(".paper-page--active") || document.querySelector("[data-presentation-engine]"))
      ),
      scenarioId,
      { timeout: 15_000 },
    );
  }

  async openPresentationScenario(scenarioId, presentation, width, height) {
    this.currentScenarioId = scenarioId;
    await this.openPath(`/?scenario=${encodeURIComponent(scenarioId)}`, width, height);
    await this.page.waitForFunction(
      ({ expectedScenarioId, expectedPresentation }) => (
        window.__PAPYRUS_SCENARIO__ === expectedScenarioId &&
        document.querySelector("[data-presentation-engine]")?.getAttribute("data-presentation-engine") === expectedPresentation
      ),
      { expectedScenarioId: scenarioId, expectedPresentation: presentation },
      { timeout: 15_000 },
    );
  }

  async openPath(path, width, height) {
    await this.close();
    this.consoleErrors = [];
    this.browser = await chromium.launch({
      headless: process.env.PAPYRUS_HEADLESS !== "false",
    });
    this.page = await this.browser.newPage({
      viewport: { width, height },
    });
    if (this.testEditorReader) {
      await this.page.addInitScript(() => {
        window.localStorage.setItem("papyrus:test-editor", "true");
      });
    }
    if (this.pendingReaderSettings) {
      const pendingReaderSettings = this.pendingReaderSettings;
      await this.page.addInitScript((settings) => {
        window.localStorage.setItem("papyrus:reader-settings", JSON.stringify(settings));
      }, pendingReaderSettings);
    }
    if (this.newsroomMessageDetailMock === "reference-curation") {
      await this.page.addInitScript(() => {
        window.localStorage.setItem("papyrus:test-newsroom-mock", JSON.stringify({
          summary: {
            generatedAt: "2026-05-20T05:34:50.280Z",
            staleAt: "2026-05-20T05:34:50.280Z",
            source: "snapshot",
            counts: {
              messages: 1,
              references: 1,
              assignments: 0,
              categorys: 0,
              semanticNodes: 0,
            },
            facets: {
              messages: {
                byKind: { reference_curation: 1 },
                byDomain: { commentary: 1 },
              },
            },
            assignmentStatusCounts: {},
            assignmentTypeCounts: {},
            referenceStatusCounts: { accepted: 1 },
            messageKindCounts: { reference_curation: 1 },
            messageDomainCounts: { commentary: 1 },
          },
          messages: [
            {
              id: "message-mock-reference-curation-001",
              messageKind: "reference_curation",
              messageDomain: "commentary",
              status: "active",
              summary: "https://example.com/papers/mock-reference.pdf: accepted",
              source: "newsroom",
              importRunId: null,
              authorSub: null,
              authorUserProfileId: null,
              authorLabel: "Test Editor",
              createdAt: "2026-05-20T05:34:50.280Z",
              updatedAt: "2026-05-20T05:34:50.280Z",
              newsroomFeedKey: "messages",
            },
          ],
          semanticRelations: [
            {
              id: "semantic-relation-mock-message-reference-001",
              relationState: "current",
              predicate: "comment",
              relationTypeId: "semantic-relation-type-comment",
              relationTypeKey: "comment",
              relationDomain: "commentary",
              subjectKind: "message",
              subjectId: "message-mock-reference-curation-001",
              subjectLineageId: "message-mock-reference-curation-001",
              subjectVersionNumber: 1,
              objectKind: "reference",
              objectId: "reference-mock-001-v1",
              objectLineageId: "reference-mock-001",
              objectVersionNumber: 1,
              subjectStateKey: "message#message-mock-reference-curation-001#current",
              objectStateKey: "reference#reference-mock-001#current",
              objectSubjectStateKey: "reference#reference-mock-001#current#message",
              predicateObjectStateKey: "comment#reference#reference-mock-001#current",
              subjectVersionKey: "message#message-mock-reference-curation-001",
              objectVersionKey: "reference#reference-mock-001-v1",
              score: null,
              confidence: null,
              rank: 1,
              classifierId: null,
              modelVersion: null,
              reviewRecommended: false,
              sourceSnapshotId: null,
              importRunId: null,
              importedAt: "2026-05-20T05:34:50.280Z",
              createdAt: "2026-05-20T05:34:50.280Z",
              updatedAt: "2026-05-20T05:34:50.280Z",
              newsroomFeedKey: "semanticRelations",
              metadata: null,
            },
          ],
          references: [
            {
              id: "reference-mock-001-v1",
              lineageId: "reference-mock-001",
              versionNumber: 1,
              versionState: "current",
              corpusId: "knowledge-corpus-mock",
              externalItemId: "mock-reference-001",
              title: "Red-Teaming for Generative AI",
              authors: ["A. Researcher"],
              sourceUri: "https://example.com/papers/mock-reference.pdf",
              mediaType: "application/pdf",
              importedAt: "2026-05-20T05:34:50.280Z",
              curationStatus: "accepted",
              curationStatusKey: "knowledge-corpus-mock#accepted",
              curationStatusUpdatedAt: "2026-05-20T05:34:50.280Z",
              curationStatusUpdatedBy: "Test Editor",
              newsroomFeedKey: "references",
              metadata: {
                title: "Red-Teaming for Generative AI",
                subtitle: "Silver Bullet or Security Theater?",
                summary: "An examination of whether red-teaming materially improves generative AI security outcomes.",
              },
              updatedAt: "2026-05-20T05:34:50.280Z",
            },
          ],
          payloads: {
            "reference:reference-mock-001-v1": [
              {
                attachment: {
                  id: "model-attachment-reference-mock-001-v1-metadata",
                  ownerKind: "reference",
                  ownerId: "reference-mock-001-v1",
                  ownerLineageId: "reference-mock-001",
                  role: "metadata",
                  sortKey: "metadata",
                  storagePath: "newsroom/payloads/reference/reference-mock-001-v1/metadata/metadata.json",
                  filename: "metadata.json",
                  mediaType: "application/json",
                  status: "active",
                },
                text: null,
                json: {
                  title: "Red-Teaming for Generative AI",
                  subtitle: "Silver Bullet or Security Theater?",
                  summary: "An examination of whether red-teaming materially improves generative AI security outcomes.",
                },
                error: null,
              },
            ],
          },
        }));
      });
    }
    if (this.newsroomReferenceSummaryPayloadMock === "dedup") {
      await this.page.addInitScript(() => {
        window.localStorage.setItem("papyrus:test-newsroom-mock", JSON.stringify({
          payloads: {
            "reference:reference-knowledge-corpus-demo-source-history-001-v1": [
              {
                attachment: {
                  id: "model-attachment-reference-history-001-metadata",
                  ownerKind: "reference",
                  ownerId: "reference-knowledge-corpus-demo-source-history-001-v1",
                  ownerLineageId: "reference-knowledge-corpus-demo-source-history-001",
                  role: "metadata",
                  sortKey: "metadata",
                  storagePath: "newsroom/payloads/reference/reference-knowledge-corpus-demo-source-history-001/metadata/metadata.json",
                  filename: "metadata.json",
                  mediaType: "application/json",
                  status: "active",
                },
                text: null,
                json: {
                  title: "Symbolic And Connectionist History Reader",
                  subtitle: "s3://papyrus-demo/corpora/history/history-001.md",
                  summary: "s3://papyrus-demo/corpora/history/history-001.md\n\nTrimmed summary body for mock reference one.",
                },
                error: null,
              },
            ],
            "reference:reference-knowledge-corpus-demo-source-history-002-v1": [
              {
                attachment: {
                  id: "model-attachment-reference-history-002-metadata",
                  ownerKind: "reference",
                  ownerId: "reference-knowledge-corpus-demo-source-history-002-v1",
                  ownerLineageId: "reference-knowledge-corpus-demo-source-history-002",
                  role: "metadata",
                  sortKey: "metadata",
                  storagePath: "newsroom/payloads/reference/reference-knowledge-corpus-demo-source-history-002/metadata/metadata.json",
                  filename: "metadata.json",
                  mediaType: "application/json",
                  status: "active",
                },
                text: null,
                json: {
                  title: "Foundation Model Scaling Retrospective",
                  summary: "Unchanged summary for mock reference two.",
                },
                error: null,
              },
            ],
          },
        }));
      });
    }
    if (this.newsroomReferenceExtractedTextMock === "history-001-filtered-and-original") {
      await this.page.addInitScript(() => {
        const key = "papyrus:test-newsroom-mock";
        let existing = {};
        try {
          const raw = window.localStorage.getItem(key);
          existing = raw ? JSON.parse(raw) : {};
        } catch {
          existing = {};
        }
        const attachmentById = new Map(Array.isArray(existing.referenceAttachments)
          ? existing.referenceAttachments.map((attachment) => [attachment.id, attachment])
          : []);
        attachmentById.set("reference-attachment-demo-history-001-extracted-text-filtered", {
          id: "reference-attachment-demo-history-001-extracted-text-filtered",
          referenceId: "reference-knowledge-corpus-demo-source-history-001-v1",
          referenceLineageId: "reference-knowledge-corpus-demo-source-history-001",
          referenceVersionNumber: 1,
          referenceVersionKey: "reference#reference-knowledge-corpus-demo-source-history-001-v1",
          role: "extracted_text",
          sortKey: "901-extracted-text-filtered",
          storagePath: "corpora/history/extracted/pipeline/snapshot-demo-history/text/filtered.txt",
          sourceUri: null,
          filename: "filtered.txt",
          mediaType: "text/plain",
          sha256: "demo-history-001-filtered-text",
          importRunId: "knowledge-import-demo-projection",
          importedAt: "2026-04-15T09:30:00.000Z",
          metadata: JSON.stringify({
            filterStatus: "filtered",
            source: "biblicus-article-text-filter",
          }),
        });
        const storageTextByPath = {
          ...(existing.storageTextByPath ?? {}),
          "corpora/history/extracted/pipeline/snapshot-demo-history/text/history-001.txt": [
            "History 001 extracted text line one.",
            "History 001 extracted text line two.",
          ].join("\n"),
          "corpora/history/extracted/pipeline/snapshot-demo-history/text/filtered.txt": [
            "History 001 filtered text line one.",
            "History 001 filtered text line two.",
          ].join("\n"),
        };
        window.localStorage.setItem(
          key,
          JSON.stringify({
            ...existing,
            referenceAttachments: Array.from(attachmentById.values()),
            storageTextByPath,
          }),
        );
      });
    }
    if (this.newsroomReferenceExtractedTextMock === "history-002-filtered-only") {
      await this.page.addInitScript(() => {
        const key = "papyrus:test-newsroom-mock";
        let existing = {};
        try {
          const raw = window.localStorage.getItem(key);
          existing = raw ? JSON.parse(raw) : {};
        } catch {
          existing = {};
        }
        const attachmentById = new Map(Array.isArray(existing.referenceAttachments)
          ? existing.referenceAttachments.map((attachment) => [attachment.id, attachment])
          : []);
        attachmentById.set("reference-attachment-demo-history-002-extracted-text-filtered", {
          id: "reference-attachment-demo-history-002-extracted-text-filtered",
          referenceId: "reference-knowledge-corpus-demo-source-history-002-v1",
          referenceLineageId: "reference-knowledge-corpus-demo-source-history-002",
          referenceVersionNumber: 1,
          referenceVersionKey: "reference#reference-knowledge-corpus-demo-source-history-002-v1",
          role: "extracted_text",
          sortKey: "901-extracted-text-filtered",
          storagePath: "corpora/history/extracted/pipeline/snapshot-demo-history/text/history-002.filtered.txt",
          sourceUri: null,
          filename: "filtered.txt",
          mediaType: "text/plain",
          sha256: "demo-history-002-filtered-text",
          importRunId: "knowledge-import-demo-projection",
          importedAt: "2026-04-16T09:30:00.000Z",
          metadata: JSON.stringify({
            filterStatus: "filtered",
            source: "biblicus-article-text-filter",
          }),
        });
        const storageTextByPath = {
          ...(existing.storageTextByPath ?? {}),
          "corpora/history/extracted/pipeline/snapshot-demo-history/text/history-002.filtered.txt": [
            "History 002 filtered text line one.",
            "History 002 filtered text line two.",
          ].join("\n"),
        };
        window.localStorage.setItem(
          key,
          JSON.stringify({
            ...existing,
            referenceAttachments: Array.from(attachmentById.values()),
            storageTextByPath,
          }),
        );
      });
    }
    if (this.newsroomQualityMutationMock === "fail") {
      await this.page.addInitScript(() => {
        window.localStorage.setItem("papyrus:test-reference-quality-mutation", "fail");
      });
    }
    if (
      this.newsroomSummaryDelayMs > 0 ||
      this.newsroomSummaryMock === "missing" ||
      this.newsroomMessageDetailMock === "reference-curation"
    ) {
      const delayMs = this.newsroomSummaryDelayMs;
      const mock = this.newsroomSummaryMock;
      const messageDetailMock = this.newsroomMessageDetailMock;
      await this.page.route("**/graphql", async (route) => {
        const request = route.request();
        const body = request.postData() ?? "";
        if (messageDetailMock === "reference-curation") {
          if (body.includes("listMessagesByNewsroomFeedAndCreatedAt")) {
            await route.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify({
                data: {
                  listMessagesByNewsroomFeedAndCreatedAt: {
                    items: [
                      {
                        id: "message-mock-reference-curation-001",
                        messageKind: "reference_curation",
                        messageDomain: "commentary",
                        status: "active",
                        summary: "https://example.com/papers/mock-reference.pdf: accepted",
                        source: "newsroom",
                        importRunId: null,
                        authorSub: null,
                        authorUserProfileId: null,
                        authorLabel: "Test Editor",
                        createdAt: "2026-05-20T05:34:50.280Z",
                        updatedAt: "2026-05-20T05:34:50.280Z",
                        newsroomFeedKey: "messages",
                      },
                    ],
                    nextToken: null,
                  },
                },
              }),
            });
            return;
          }
          if (body.includes("listSemanticRelationsByNewsroomFeedAndCreatedAt")) {
            await route.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify({
                data: {
                  listSemanticRelationsByNewsroomFeedAndCreatedAt: {
                    items: [
                      {
                        id: "semantic-relation-mock-message-reference-001",
                        relationState: "current",
                        predicate: "comment",
                        relationTypeId: "semantic-relation-type-comment",
                        relationTypeKey: "comment",
                        relationDomain: "commentary",
                        subjectKind: "message",
                        subjectId: "message-mock-reference-curation-001",
                        subjectLineageId: "message-mock-reference-curation-001",
                        subjectVersionNumber: 1,
                        objectKind: "reference",
                        objectId: "reference-mock-001-v1",
                        objectLineageId: "reference-mock-001",
                        objectVersionNumber: 1,
                        subjectStateKey: "message#message-mock-reference-curation-001#current",
                        objectStateKey: "reference#reference-mock-001#current",
                        objectSubjectStateKey: "reference#reference-mock-001#current#message",
                        predicateObjectStateKey: "comment#reference#reference-mock-001#current",
                        subjectVersionKey: "message#message-mock-reference-curation-001",
                        objectVersionKey: "reference#reference-mock-001-v1",
                        score: null,
                        confidence: null,
                        rank: 1,
                        classifierId: null,
                        modelVersion: null,
                        reviewRecommended: false,
                        sourceSnapshotId: null,
                        importRunId: null,
                        importedAt: "2026-05-20T05:34:50.280Z",
                        createdAt: "2026-05-20T05:34:50.280Z",
                        updatedAt: "2026-05-20T05:34:50.280Z",
                        newsroomFeedKey: "semanticRelations",
                        metadata: null,
                      },
                    ],
                    nextToken: null,
                  },
                },
              }),
            });
            return;
          }
          if (body.includes("getReference")) {
            await route.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify({
                data: {
                  getReference: {
                    id: "reference-mock-001-v1",
                    lineageId: "reference-mock-001",
                    versionNumber: 1,
                    previousVersionId: null,
                    versionState: "current",
                    versionCreatedAt: null,
                    versionCreatedBy: null,
                    changeReason: null,
                    contentHash: null,
                    corpusId: "knowledge-corpus-mock",
                    externalItemId: "mock-reference-001",
                    title: "Red-Teaming for Generative AI",
                    authors: ["A. Researcher"],
                    sourceUri: "https://example.com/papers/mock-reference.pdf",
                    storagePath: null,
                    mediaType: "application/pdf",
                    byteSize: null,
                    sha256: null,
                    sourcePublishedAt: null,
                    sourceUpdatedAt: null,
                    retrievedAt: null,
                    importRunId: null,
                    importedAt: "2026-05-20T05:34:50.280Z",
                    createdAt: "2026-05-20T05:34:50.280Z",
                    curationStatus: "accepted",
                    curationStatusKey: "knowledge-corpus-mock#accepted",
                    curationStatusUpdatedAt: "2026-05-20T05:34:50.280Z",
                    curationStatusUpdatedBy: "Test Editor",
                    curationStatusReason: null,
                    newsroomFeedKey: "references",
                    metadata: {
                      title: "Red-Teaming for Generative AI",
                      subtitle: "Silver Bullet or Security Theater?",
                    },
                    updatedAt: "2026-05-20T05:34:50.280Z",
                  },
                },
              }),
            });
            return;
          }
          if (body.includes("listModelAttachmentsByOwnerRoleAndSortKey")) {
            await route.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify({
                data: {
                  listModelAttachmentsByOwnerRoleAndSortKey: {
                    items: [],
                    nextToken: null,
                  },
                },
              }),
            });
            return;
          }
          if (body.includes("getNewsroomSummary")) {
            const now = new Date().toISOString();
            await route.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify({
                data: {
                  getNewsroomSummary: {
                    generatedAt: now,
                    staleAt: now,
                    source: "snapshot",
                    counts: {
                      messages: 1,
                      references: 1,
                      assignments: 0,
                      categorys: 0,
                      semanticNodes: 0,
                    },
                    facets: {
                      messages: {
                        byKind: { reference_curation: 1 },
                        byDomain: { commentary: 1 },
                      },
                    },
                    assignmentStatusCounts: {},
                    assignmentTypeCounts: {},
                    referenceStatusCounts: { accepted: 1 },
                    messageKindCounts: { reference_curation: 1 },
                    messageDomainCounts: { commentary: 1 },
                  },
                },
              }),
            });
            return;
          }
        }
        if (!body.includes("getNewsroomSummary")) {
          await route.continue();
          return;
        }
        if (delayMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, delayMs));
        }
        if (mock === "missing") {
          const now = new Date().toISOString();
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              data: {
                getNewsroomSummary: {
                  generatedAt: now,
                  staleAt: now,
                  source: "missing",
                  counts: {},
                  facets: {},
                  assignmentStatusCounts: {},
                  assignmentTypeCounts: {},
                  referenceStatusCounts: {},
                  messageKindCounts: {},
                  messageDomainCounts: {},
                },
              },
            }),
          });
          return;
        }
        await route.continue();
      });
    }
    this.page.on("console", (message) => {
      if (message.type() === "error") {
        this.consoleErrors.push(message.text());
      }
    });

    const url = new URL(path, this.baseUrl);
    await this.page.goto(url.toString(), { waitUntil: "load" });
    await this.readCapabilitiesFromActivePage();
  }

  async close() {
    if (this.browser) {
      await this.browser.close();
    }
    this.browser = null;
    this.page = null;
  }
}

setWorldConstructor(PapyrusWorld);

Before(async function ({ pickle }) {
  await this.probeSiteCapabilities();
  const skipReason = shouldSkipScenario(this, pickle.tags);
  if (skipReason) {
    return "skipped";
  }
});

After(async function () {
  await this.close();
});
