import type { AssignmentRecord, MessageRecord, ReferenceRecord, SemanticRelationRecord } from "./category-repository";
import { SHADOW_AGREEMENT_SCHEMA, type ShadowAgreement } from "./cyclotron-suggestions";
import type { EditableArticle } from "./newsroom-articles";
import type { MediaAssetRecord } from "./newsroom-media";
import type { ResearchAssignmentPlan } from "./assign-research";
import type { ResearchPacketView } from "./research-packet";
import { EMPTY_STORY_REPORTING_TRAIL, type ReferenceStory, type StoryReportingTrail, type TrailAgentNote, type TrailAssignment, type TrailReference, type TrailThread, type TrailVersion } from "./story-reporting-trail";
import { contentItemHeadStageKey, contentItemStageKeys, type ContentItemVersionRecord } from "./content-item-lifecycle";
import { getContentItemStageDefinitions } from "./site-brand";
import { noteProblem, stepChangeProblem, summarizeStoryChecklist, type StoryStepNote, type StoryStepRecord } from "./story-checklist";
import { LOCAL_PREVIEW_TENANTS, getLocalPreviewTenantId } from "./local-preview-tenant";

const SEED_TIMESTAMP_BASE = Date.parse("2026-10-01T12:00:00.000Z");
const ONE_HOUR_IN_MILLISECONDS = 60 * 60 * 1000;

const SEED_CONTENT_ITEM_HEADLINES_BY_POSITION_FOR_TENANT_ZERO: readonly (readonly string[])[] = [
  ["Three sources confirm the zoning reversal", "Reporting packet: school board redistricting"],
  ["Draft in progress: the last ferry crossing", "Draft in progress: neighborhood bakery profile"],
  ["Illustration brief: flooded streets, aerial view", "Illustration brief: the market at dawn"],
  ["Layout pass: front page lead and rail", "Layout pass: the Saturday supplement"],
  ["Published: harbor safety review", "Published: the lighthouse keepers' archive"],
  ["Held for the winter issue: the lighthouse keepers' archive", "Evergreen: how the harbor dredging works"],
  ["Spiked: the unconfirmed council rumor", "Spiked: the recycled press release"],
];

const SEED_CONTENT_ITEM_HEADLINES_BY_POSITION_FOR_TENANT_ONE: readonly (readonly string[])[] = [
  ["Field note: spore dispersal on a damp morning", "Field note: the dung beetle census"],
  ["Draft in progress: why fungi throw their caps", "Draft in progress: the compost experiment"],
  ["Illustration brief: a cap in flight, close up", "Illustration brief: the mycelium network"],
  ["Layout pass: the monthly field guide", "Layout pass: the reader mailbag"],
  ["Published: a season of mushroom sightings", "Published: how the forest floor recycles"],
  ["Held for spring: the truffle hunt", "Evergreen: a beginner's guide to identification"],
  ["Spiked: the unverified foraging claim", "Spiked: the duplicate field report"],
];

const SEED_CONTENT_ITEM_HEADLINES_BY_TENANT = [SEED_CONTENT_ITEM_HEADLINES_BY_POSITION_FOR_TENANT_ZERO, SEED_CONTENT_ITEM_HEADLINES_BY_POSITION_FOR_TENANT_ONE] as const;

function headlinesForSelectedTenant(): readonly (readonly string[])[] {
  const tenantId = getLocalPreviewTenantId();
  const tenant = LOCAL_PREVIEW_TENANTS.find(candidate => candidate.accountId === tenantId) ?? LOCAL_PREVIEW_TENANTS[0];
  return SEED_CONTENT_ITEM_HEADLINES_BY_TENANT[tenant.fixtureHeadlineSet] ?? SEED_CONTENT_ITEM_HEADLINES_BY_TENANT[0];
}

function isoTimestampHoursBeforeBase(hours: number): string {
  return new Date(SEED_TIMESTAMP_BASE - hours * ONE_HOUR_IN_MILLISECONDS).toISOString();
}

function slugFromHeadline(headline: string): string {
  return headline.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

/** Sample ratings the preview Stories already carry (a Story's private 1-5 stars), so the board, the drawer and the editor show some. */
const PREVIEW_STORY_STARS: Readonly<Record<string, number>> = {
  "copywriting-0": 4,
  "published-0": 5,
  "idea-1": 2,
};

/** The template, as the preview shows it: the live steps of the Story procedure (src/papyrus_content/newsroom_process.py), in order. */
const PREVIEW_CHECKLIST_TEMPLATE: readonly { key: string; title: string; command: string; required: boolean }[] = [
  { key: "choose", title: "Choose the idea", command: "papyrus ideas select --section <section>", required: true },
  { key: "direction", title: "Give the research direction", command: "papyrus stories assign-research --story {story} --direction-file direction.md", required: true },
  { key: "research", title: "Research the Story", command: "papyrus assignments research-multi <assignment id>", required: true },
  { key: "outline", title: "Write the outline after the research", command: "papyrus stories outline --story {story}", required: true },
  { key: "draft", title: "Write the draft", command: "papyrus stories draft --story {story}", required: true },
  { key: "copy_edit", title: "Copy-edit the draft", command: "papyrus editorial check-version --item <current version id>", required: true },
  { key: "review_people", title: "Reviewed for readers", command: "papyrus stories step --story {story} --step review_people --state done --note <findings>", required: true },
  { key: "review_reader_agents", title: "Reviewed for AI reader agents", command: "papyrus stories step --story {story} --step review_reader_agents --state done --note <findings>", required: true },
  { key: "review_search", title: "Reviewed for search", command: "papyrus stories step --story {story} --step review_search --state done --note <findings>", required: true },
  { key: "review_social", title: "Reviewed for social previews", command: "papyrus stories step --story {story} --step review_social --state done --note <findings>", required: true },
  { key: "publish", title: "Publish the Story", command: "papyrus ops content publish --id <item id>", required: false },
];
const PREVIEW_CHECKLIST_TEMPLATE_VERSION = 2;
const PREVIEW_CHECKLIST_EVIDENCE_SOURCES: Record<string, string> = {
  choose: "the Story's stage", direction: "the research direction", research: "the research packet", outline: "the outline", draft: "the draft version",
  copy_edit: "the copy-edit check", publish: "publishing",
};

/** Notes the preview steps already carry, so the panel shows an open, a closed and a crowded step: the log is newest last. */
function previewNotesFor(lineageId: string, key: string): StoryStepNote[] {
  if (lineageId !== "preview-item-lineage-copywriting-0") return [];
  if (key === "review_people") return [
    { at: "2026-10-01T05:30:00.000Z", actorKind: "agent", actorLabel: "AI", text: "Headline and dek agree with the opening paragraph." },
    { at: "2026-10-01T06:10:00.000Z", actorKind: "person", actorLabel: "Preview editor", text: "The second section is long. Leave it for now, but trim it if the Story runs again.\nThe quotation in the fourth paragraph needs its source named." },
    { at: "2026-10-01T07:45:00.000Z", actorKind: "person", actorLabel: "Sierra", text: "Correction to the note above: the quotation is already sourced in the footer." },
    { at: "2026-10-01T09:00:00.000Z", actorKind: "agent", actorLabel: "AI", text: "Checked the footer: the source is named there." },
  ];
  if (key === "outline") return [{ at: "2026-10-01T08:20:00.000Z", actorKind: "person", actorLabel: "Preview editor", text: "Skipped on purpose: this Story came from a single Reference." }];
  if (key === "review_search") return [{ at: "2026-10-01T09:30:00.000Z", actorKind: "person", actorLabel: "Sierra", text: "Waiting on the section editor to choose the final headline." }];
  return [];
}

/** How far each preview Story's checklist has got, so a card and a panel show open, done, skipped and not-applicable steps. */
function previewChecklistFor(stageKey: string, headlineIndex: number, lineageId: string): StoryStepRecord[] {
  const stageOrder = ["idea", "assignment", "reporting", "copywriting", "illustration", "typesetting", "published"];
  const reached = Math.max(0, stageOrder.indexOf(stageKey));
  const doneBy = (key: string): number => ({ choose: 1, direction: 1, research: 2, outline: 2, draft: 3, copy_edit: 3, publish: 6 } as Record<string, number>)[key] ?? 99;
  return PREVIEW_CHECKLIST_TEMPLATE.map((entry, index): StoryStepRecord => {
    const base = {
      id: `step-${lineageId}-${entry.key}`, storyLineageId: lineageId, stepKey: entry.key, stepOrder: index, templateVersion: PREVIEW_CHECKLIST_TEMPLATE_VERSION,
      title: entry.title, command: entry.command.replace("{story}", lineageId), state: "open" as const, notes: previewNotesFor(lineageId, entry.key),
    };
    const changedAt = isoTimestampHoursBeforeBase(index + 1);
    if (stageKey === "published" && entry.key.startsWith("review_")) {
      return entry.key === "review_social"
        ? { ...base, state: "not_applicable", actorKind: "person", actorLabel: "Preview editor", changedAt, reason: "This Story has no image to preview." }
        : { ...base, state: "done", actorKind: "agent", actorLabel: "Reviewing agent", changedAt, note: "Read as a reader would: the headline, deck and first paragraph hold up." };
    }
    if (entry.key === "outline" && reached >= 3 && headlineIndex === 0) {
      return { ...base, state: "skipped", actorKind: "person", actorLabel: "Preview editor", changedAt, reason: "The editor wrote the draft straight from the reporting notes." };
    }
    if (entry.key === "review_people" && reached === 3 && headlineIndex === 0) {
      return { ...base, state: "done", actorKind: "person", actorLabel: "Preview editor", changedAt, note: "Reads clearly; the second section is long but earns its length." };
    }
    if (reached >= doneBy(entry.key) && !entry.key.startsWith("review_")) {
      return { ...base, state: "done", actorKind: "system", actorLabel: `Automatically, from ${PREVIEW_CHECKLIST_EVIDENCE_SOURCES[entry.key] ?? "the records"}`, changedAt, evidence: `Preview record for ${entry.key}` };
    }
    return base;
  });
}

/** Changes made in the preview (the panel's buttons): the preview has no backend, so a Story's steps are kept here once one is changed. */
const previewChecklistChanges = new Map<string, StoryStepRecord[]>();

function previewChecklistOf(lineageId: string): StoryStepRecord[] {
  const changed = previewChecklistChanges.get(lineageId);
  if (changed) return changed;
  const match = /^preview-item-lineage-(.+)-(\d+)$/.exec(lineageId);
  return match ? previewChecklistFor(match[1], Number(match[2]), lineageId) : [];
}

/** The checklist steps of a preview Story (the index read the panel makes against the real backend). */
export function createLocalPreviewStoryChecklist(lineageId: string): StoryStepRecord[] {
  return previewChecklistOf(lineageId).map(step => ({ ...step }));
}

/** What the backend does for `setStoryStep`, for the preview: the same rules, the change recorded as the preview editor. */
export function setLocalPreviewStoryStep(lineageId: string, stepKey: string, state: StoryStepRecord["state"], input: { reason?: string; note?: string }): void {
  const problem = stepChangeProblem(stepKey, state, input);
  if (problem) throw new Error(problem);
  const steps = previewChecklistOf(lineageId);
  if (!steps.some(step => step.stepKey === stepKey)) throw new Error(`Unknown step ${stepKey}.`);
  previewChecklistChanges.set(lineageId, steps.map(step => step.stepKey !== stepKey ? step : {
    ...step, state, actorKind: "person", actorLabel: "Preview editor", changedAt: new Date().toISOString(),
    reason: state === "skipped" || state === "not_applicable" ? input.reason?.trim() ?? null : null, note: input.note?.trim() || null, evidence: null,
  }));
}

/** What the backend does for a note, for the preview: appended to the step's log, as the preview editor, whatever the step's state. */
export function addLocalPreviewStoryStepNote(lineageId: string, stepKey: string, text: string): void {
  const problem = noteProblem(text);
  if (problem) throw new Error(problem);
  const steps = previewChecklistOf(lineageId);
  if (!steps.some(step => step.stepKey === stepKey)) throw new Error(`Unknown step ${stepKey}.`);
  previewChecklistChanges.set(lineageId, steps.map(step => step.stepKey !== stepKey ? step : {
    ...step, notes: [...step.notes, { at: new Date().toISOString(), actorKind: "person", actorLabel: "Preview editor", text: text.trim() }],
  }));
}

/** Forgets the preview's changes (a test starts from the sample steps). */
export function resetLocalPreviewStoryChecklists(): void {
  previewChecklistChanges.clear();
}

export function createLocalPreviewContentItemVersions(): ContentItemVersionRecord[] {
  const stageKeys = contentItemStageKeys(getContentItemStageDefinitions());
  return stageKeys.flatMap((stageKey, stageIndex) => {
    const tenantHeadlines = headlinesForSelectedTenant();
    const headlines = tenantHeadlines[stageIndex % tenantHeadlines.length];
    return headlines.map((headline, headlineIndex) => {
      const slug = slugFromHeadline(headline);
      return {
        id: `preview-item-version-${stageKey}-${headlineIndex}`,
        lineageId: `preview-item-lineage-${stageKey}-${headlineIndex}`,
        versionNumber: 1,
        stage: stageKey,
        headStageKey: contentItemHeadStageKey({ stage: stageKey, versionState: "current" }),   // each sample story is its own one-row lineage
        type: "article",
        status: stageKey === "published" ? "published" : "draft",
        title: headline,
        headline,
        slug,
        section: headlineIndex === 0 ? "news" : "features",
        updatedAt: isoTimestampHoursBeforeBase(stageIndex * 3 + headlineIndex),
        versionCreatedBy: stageKey === "idea" && headlineIndex === 0 ? "AI" : "Preview editor",
        starRating: PREVIEW_STORY_STARS[`${stageKey}-${headlineIndex}`] ?? null,
        metadata: { checklist: summarizeStoryChecklist(previewChecklistOf(`preview-item-lineage-${stageKey}-${headlineIndex}`), PREVIEW_CHECKLIST_TEMPLATE.filter(entry => entry.required).map(entry => entry.key), PREVIEW_CHECKLIST_TEMPLATE_VERSION) },
      };
    });
  });
}

/** Sample References that were accepted without an editor, for the "Accepted automatically" list: written as the router writes them. */
const PREVIEW_AUTO_ACCEPTED: ReadonlyArray<{ title: string; host: string; hoursAgo: number; actor: "auto:cyclotron" | "auto:rule" | "editor"; confidence?: number; monitor?: string }> = [
  { title: "Harbor commission publishes its dredging schedule for the winter", host: "harbor-commission.example.test", hoursAgo: 3, actor: "auto:cyclotron", confidence: 0.97 },
  { title: "Daily ferry timetable, revised", host: "ferries.example.test", hoursAgo: 9, actor: "auto:rule", monitor: "ferry-notices" },
  { title: "What the school board's redistricting maps leave out", host: "ledger.example.test", hoursAgo: 14, actor: "auto:cyclotron", confidence: 0.93 },
  { title: "Zoning reversal: the three documents behind the vote", host: "city-records.example.test", hoursAgo: 20, actor: "editor" },
  { title: "Lighthouse keepers' logbooks, digitised", host: "archive.example.test", hoursAgo: 31, actor: "auto:cyclotron", confidence: 0.91 },
  { title: "Council meeting agenda, week 44", host: "council.example.test", hoursAgo: 40, actor: "auto:rule", monitor: "council-agendas" },
  { title: "A bakery that outlasted four recessions", host: "market-gazette.example.test", hoursAgo: 55, actor: "auto:cyclotron", confidence: 0.9 },
];

/**
 * What the preview holds of each sample Reference (`Reference.captureState`, the rule in lib/reference-capture.ts): some captured, some cut off,
 * some only an address, one still being captured, so the Captured filter and the home page's capture list have something to show.
 */
const PREVIEW_AUTO_CAPTURE_STATES: readonly string[] = ["none", "thin", "full", "none", "running", "full", "thin"];
const PREVIEW_CAPTURE_STATES: readonly string[] = ["none", "none", "full", "none", "none"];

function previewAutoAcceptedReason(plan: (typeof PREVIEW_AUTO_ACCEPTED)[number]): string {
  if (plan.actor === "auto:rule") {
    return `Accepted automatically by the ${plan.monitor} monitor's rule (every collected item): it delivers only items that match the rule, so there is no relevance prediction and the match is the acceptance. An editor can still Reject it.`;
  }
  return `Accepted automatically by the Cyclotron: it was ${((plan.confidence ?? 0) * 100).toFixed(1)}% sure this is relevant, at or above the 90.0% learned from 42 editor votes (estimated accept rate 97.6%, 95% lower bound 91.0%, target 90%), and nobody voted within 2.0 days, the 90% quantile of how long editors take. An editor can still Reject it.`;
}

export function createLocalPreviewReferences(): ReferenceRecord[] {
  const curationStatuses = ["pending", "accepted", "accepted", "rejected", "pending"];
  const autoAccepted: ReferenceRecord[] = PREVIEW_AUTO_ACCEPTED.map((plan, index) => {
    const at = isoTimestampHoursBeforeBase(plan.hoursAgo);
    const editor = plan.actor === "editor";
    return {
      id: `preview-auto-reference-${index}`,
      lineageId: `preview-auto-reference-lineage-${index}`,
      versionNumber: 1,
      versionState: "current",
      corpusId: "preview-corpus",
      externalItemId: `preview-auto-source-${index}`,
      title: plan.title,
      sourceUri: `https://${plan.host}/story-${index + 1}`,
      curationStatus: "accepted",
      curationStatusKey: "preview-corpus#accepted",
      curationStatusUpdatedAt: at,
      curationStatusUpdatedBy: editor ? "preview-editor" : plan.actor,
      curationStatusReason: editor ? "Primary source for the zoning story." : previewAutoAcceptedReason(plan),
      curationActorKind: editor ? "human" : plan.actor === "auto:rule" ? "rule" : "cyclotron",
      importedAt: isoTimestampHoursBeforeBase(plan.hoursAgo + 50),
      captureState: PREVIEW_AUTO_CAPTURE_STATES[index] ?? "full",
      updatedAt: at,
      // One rated, one rated low, the rest unrated: the preview shows filled and empty stars (the shape is the difference).
      ...(index === 0 ? { starRating: 5, starRatedAt: at, starRatedBy: "preview-editor" } : index === 1 ? { starRating: 2, starRatedAt: at, starRatedBy: "preview-editor" } : {}),
    };
  });
  const sampled = curationStatuses.map((curationStatus, index): ReferenceRecord => ({
    id: `preview-reference-${index}`,
    lineageId: `preview-reference-lineage-${index}`,
    versionNumber: 1,
    versionState: "current",
    corpusId: "preview-corpus",
    externalItemId: `preview-source-${index}`,
    title: `Source document ${index + 1}: municipal filing excerpt`,
    curationStatus,
    curationStatusKey: curationStatus,
    curationStatusReason: curationStatus === "rejected" ? "Duplicate of an earlier filing." : null,
    importedAt: isoTimestampHoursBeforeBase(index * 5),
    captureState: PREVIEW_CAPTURE_STATES[index] ?? "none",
    updatedAt: isoTimestampHoursBeforeBase(index * 5),
    ...(index === 1 ? { starRating: 4, starRatedAt: isoTimestampHoursBeforeBase(5), starRatedBy: "preview-editor" } : {}),
  }));
  return [...sampled, ...autoAccepted];
}

export function createLocalPreviewAssignments(): AssignmentRecord[] {
  const contentItemVersions = createLocalPreviewContentItemVersions();
  const assignmentTypeKeys = ["research", "reporting", "copywriting"];
  const statuses = ["queued", "claimed", "completed"];
  const assignmentsOnContentItems = contentItemVersions.slice(0, 9).map((version, index) => ({
    id: `preview-assignment-${index}`,
    assignmentTypeKey: assignmentTypeKeys[index % assignmentTypeKeys.length],
    queueKey: assignmentTypeKeys[index % assignmentTypeKeys.length],
    queueStatusKey: `${assignmentTypeKeys[index % assignmentTypeKeys.length]}#${statuses[index % statuses.length]}`,
    status: statuses[index % statuses.length],
    priority: 2,
    title: `${assignmentTypeKeys[index % assignmentTypeKeys.length]} for: ${version.headline}`,
    itemLineageId: version.lineageId,
    createdAt: isoTimestampHoursBeforeBase(index * 2),
    updatedAt: isoTimestampHoursBeforeBase(index * 2),
  }));
  const assignmentsWithoutContentItem = ["Pitch: community radio partnership", "Backfill the archive index"].map((title, index) => ({
    id: `preview-assignment-standalone-${index}`,
    assignmentTypeKey: "research",
    queueKey: "research",
    queueStatusKey: "research#queued",
    status: "queued",
    priority: 2,
    title,
    createdAt: isoTimestampHoursBeforeBase(index),
    updatedAt: isoTimestampHoursBeforeBase(index),
  }));
  return [...assignmentsOnContentItems, ...assignmentsWithoutContentItem];
}

export function createLocalPreviewRealPublishedVersions(): ContentItemVersionRecord[] {
  return [];
}

export function createLocalPreviewEditableArticle(id: string): EditableArticle | null {
  const version = createLocalPreviewContentItemVersions().find(candidate => candidate.id === id);
  if (!version) return null;
  const headline = version.headline || version.title || version.slug;
  return {
    id: version.id,
    lineageId: version.lineageId,
    type: version.type,
    section: version.section ?? null,
    slug: version.slug,
    frontMatterYaml: `title: ${headline}\nsection: ${version.section ?? ""}`,
    bodyMarkus: `# ${headline}\n\nThe local preview shows this story's record. Its full body text is loaded from the live backend.`,
    contentHash: null,
    status: version.status === "published" ? "published" : "draft",
    versionNumber: version.versionNumber,
    aliases: [],
    everPublished: version.status === "published",
    starRating: version.starRating ?? null,
  };
}

export function recordLocalPreviewDesk(articleId: string, deskId: string | null): void {
  const version = createLocalPreviewContentItemVersions().find(candidate => candidate.id === articleId);
  if (version) version.section = deskId;
}

const previewSavedVersions = new Map<string, TrailVersion[]>();
const previewLineageByVersionId = new Map<string, string>();

export function recordLocalPreviewVersion(lineageId: string, version: TrailVersion): void {
  previewSavedVersions.set(lineageId, [version, ...(previewSavedVersions.get(lineageId) ?? [])]);
  previewLineageByVersionId.set(version.id, lineageId);
}

export function lineageForPreviewVersion(versionId: string): string | null {
  return previewLineageByVersionId.get(versionId) ?? null;
}

/** The demo story that is based on a demo Reference, so the story view and the Reference view can show the link without a backend. */
const PREVIEW_BASED_ON = {
  storyLineageId: "demo-article-published",
  storyTitle: "Harbor Cranes Return",
  referenceLineageId: "reference-knowledge-corpus-demo-source-history-002",
};
const PREVIEW_IMAGE = "data:image/svg+xml;utf8," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="96" height="72"><rect width="96" height="72" fill="#cbd5c0"/></svg>');

function previewBasedOnReference(): TrailReference {
  return {
    relationId: "preview-story-reference-relation", predicate: "uses_evidence", referenceId: "reference-knowledge-corpus-demo-source-history-002", referenceLineageId: PREVIEW_BASED_ON.referenceLineageId,
    title: "Foundation Model Scaling Retrospective", sourceUri: "https://history.example.org/scaling-retrospective", siteName: "history.example.org", previewImageUrl: PREVIEW_IMAGE,
    role: "based_on", note: null, citationKey: null, addedBy: "papyrus-cli", addedAt: isoTimestampHoursBeforeBase(30),
  };
}

const previewAssignments = new Map<string, TrailAssignment[]>();

/** A research assignment made in the local preview: it stays `open`, because no worker runs there. */
export function recordLocalPreviewAssignment(lineageId: string, plan: ResearchAssignmentPlan): void {
  const created = String(plan.assignment.createdAt);
  const assignment: TrailAssignment = {
    id: plan.assignment.id, title: String(plan.assignment.title), assignmentTypeKey: String(plan.assignment.assignmentTypeKey), status: "open", assigneeKey: null, summary: null,
    createdAt: created, direction: String(plan.metadata.direction),
    events: [{ id: plan.event.id, eventType: "created", fromStatus: null, toStatus: "open", actorLabel: "You", note: String(plan.event.note), createdAt: created }],
  };
  previewAssignments.set(lineageId, [assignment, ...(previewAssignments.get(lineageId) ?? [])]);
}

const PREVIEW_PACKET: ResearchPacketView = {
  summary: "The harbor authority approved the crane contract in March, and two independent filings agree on the cost. Delivery dates differ between the authority and the contractor.",
  recommendedAngle: "Lead with the cost both filings agree on, then the dispute over delivery dates.",
  claims: [
    { claim: "The authority approved a contract for four cranes in March.", sources: [
      { rank: 1, url: "https://authority.example.org/minutes/march", title: "March board minutes", domain: "authority.example.org" },
      { rank: 2, url: "https://news.example.net/cranes-approved", title: "Cranes approved for the harbor", domain: "news.example.net" }] },
    { claim: "Delivery is scheduled to start in September.", snippetOnly: true, sources: [{ rank: 3, url: "https://contractor.example.com/schedule", title: "Delivery schedule", domain: "contractor.example.com" }] },
    { claim: "The contract is worth 41 million dollars.", sources: [{ rank: 2, url: "https://news.example.net/cranes-approved", title: "Cranes approved for the harbor", domain: "news.example.net" }] },
  ],
  disagreements: [{ topic: "Delivery date", positions: [
    { position: "The authority says the first crane arrives in June.", sources: [{ rank: 1, url: "https://authority.example.org/minutes/march", title: "March board minutes", domain: "authority.example.org" }] },
    { position: "The contractor says September.", sources: [{ rank: 3, url: "https://contractor.example.com/schedule", title: "Delivery schedule", domain: "contractor.example.com" }] }] }],
  openQuestions: ["Who pays for the rail spur the cranes need?", "Was the second bidder disqualified?"],
  unverifiedClaims: [
    { claim: "The contractor has delivered late on two earlier harbor projects.", verdict: "needs_check", sources: [{ rank: 3, url: "https://contractor.example.com/schedule", title: "Delivery schedule", domain: "contractor.example.com" }], reasons: ["The source only partly supports this"] },
    { claim: "Delivery will start in July.", verdict: "contradicted", sources: [{ rank: 3, url: "https://contractor.example.com/schedule", title: "Delivery schedule", domain: "contractor.example.com" }], reasons: ["A source says otherwise"] },
    { claim: "Mayor Rodney Hale signed the contract in March.", verdict: "not_shown", sources: [{ rank: 1, url: "https://authority.example.org/minutes/march", title: "March board minutes", domain: "authority.example.org" }], reasons: ["Not in the cited source: Rodney"] },
    { claim: "The second bidder withdrew.", verdict: "unchecked", sources: [{ rank: 2, url: "https://news.example.net/cranes-approved", title: "Cranes approved for the harbor", domain: "news.example.net" }], reasons: ["The run ran short of time before this claim was checked"] },
  ],
  factCheckSummary: "12 verified, 8 need a check, 2 contradicted, 6 not shown by the sources; 23 rest on one site",
  readingSummary: "Read 2 of 3 sources, 1 of them in part. 1 could not be opened, so claims from them rest on search snippets.",
  notOpened: ["https://contractor.example.com/schedule"],
  directionGaps: [],
  sourceCount: 3,
};

function previewResearchAssignments(): TrailAssignment[] {
  const at = (hours: number) => isoTimestampHoursBeforeBase(hours);
  const research = (id: string, status: string, hours: number, direction: string, events: TrailAssignment["events"], packet: ResearchPacketView | null = null): TrailAssignment => ({
    id, title: "Harbor Cranes Return", assignmentTypeKey: "research.multi", status, assigneeKey: status === "open" ? null : "papyrus-research-worker", summary: null, createdAt: at(hours), direction, packet, events,
  });
  const event = (id: string, eventType: string, toStatus: string, hours: number, note: string, fromStatus: string | null = null) => ({ id, eventType, fromStatus, toStatus, actorLabel: eventType === "created" ? "An Editor" : "papyrus-research-worker", note, createdAt: at(hours) });
  return [
    research("preview-research-waiting", "open", 1, "Find out whether the contractor has missed deadlines on other harbor work.", [event("w1", "created", "open", 1, "Created research assignment: Harbor Cranes Return")]),
    research("preview-research-running", "claimed", 3, "Check the cost figure against the authority's budget filings.", [event("r1", "created", "open", 3, "Created research assignment: Harbor Cranes Return"), event("r2", "claim", "claimed", 2.5, "The research worker started this assignment.", "open")]),
    research("preview-research-failed", "failed", 8, "List the other ports that bought cranes from the same maker.", [event("f1", "created", "open", 8, "Created research assignment: Harbor Cranes Return"), event("f2", "claim", "claimed", 7.5, "The research worker started this assignment.", "open"), event("f3", "research.failed", "failed", 7, "multi-search found no sources: no search provider answered", "claimed")]),
    research("preview-research-finished", "completed", 20, "Confirm the contract date and amount, and find where the sources disagree.", [event("d1", "created", "open", 20, "Created research assignment: Harbor Cranes Return"), event("d2", "claim", "claimed", 19.5, "The research worker started this assignment.", "open"), event("d3", "research.completed", "completed", 19, "Research finished; the packet is on the assignment.", "claimed")], PREVIEW_PACKET),
  ];
}

export function createLocalPreviewReportingTrail(lineageId: string): StoryReportingTrail {
  const saved = previewSavedVersions.get(lineageId) ?? [];
  const references = lineageId === PREVIEW_BASED_ON.storyLineageId ? [previewBasedOnReference()] : [];
  const assignments = [...(previewAssignments.get(lineageId) ?? []), ...(lineageId === PREVIEW_BASED_ON.storyLineageId ? previewResearchAssignments() : [])];
  const basedOn = lineageId === PREVIEW_BASED_ON.storyLineageId;
  return { ...EMPTY_STORY_REPORTING_TRAIL, versions: saved, references, assignments, threads: basedOn ? [previewStoryThread()] : [], agentNotes: basedOn ? previewAgentNotes() : [] };
}

function previewStoryThread(): TrailThread {
  return { id: "preview-story-thread", title: PREVIEW_BASED_ON.storyTitle, threadKind: "story_reporting", summary: null, messages: [
    { id: "preview-story-message-1", sequenceNumber: 1, messageKind: "note", authorLabel: "ryan", summary: "Check the second source before we lean on it", content: "The vendor post is the only source for the benchmark number. Ask for the paper.", createdAt: "2026-11-03T14:05:00Z" },
  ] };
}

/** Two synthetic AI agent notes, one tied to a draft version, for reviewing how the trail labels them. */
function previewAgentNotes(): TrailAgentNote[] {
  return [
    { id: "preview-agent-note-1", agent: "ChatGPT", summary: "The vendor's benchmark matches the paper's table 3", body: "Compared the vendor post with the paper. The headline figure matches table 3; the post leaves out the two failed runs reported in the appendix.\n\nOpen question: which hardware the vendor used.", referenceLineageId: null, versionNumber: 2, createdAt: "2026-11-03T14:20:00Z" },
    { id: "preview-agent-note-2", agent: "Claude", summary: "No second independent replication found", body: "Searched the usual venues and two preprint servers. Nobody has replicated the result yet.", referenceLineageId: null, versionNumber: null, createdAt: "2026-11-03T13:10:00Z" },
  ];
}

export function createLocalPreviewStoriesForReference(referenceLineageId: string): ReferenceStory[] {
  if (referenceLineageId !== PREVIEW_BASED_ON.referenceLineageId) return [];
  return [{ relationId: "preview-story-reference-relation", itemId: PREVIEW_BASED_ON.storyLineageId, lineageId: PREVIEW_BASED_ON.storyLineageId, title: PREVIEW_BASED_ON.storyTitle, stage: "copywriting", role: "based_on" }];
}

export function createLocalPreviewMediaAssets(_itemId: string): MediaAssetRecord[] {
  return [];
}

type PreviewSuggestionPlan = {
  label: "include" | "exclude";
  confidence: number;
  curation: "none" | "human" | "service" | "delegated";
  provenance: boolean;
};

const PREVIEW_SUGGESTION_PLANS: readonly PreviewSuggestionPlan[] = [
  { label: "include", confidence: 0.91, curation: "none", provenance: true },
  { label: "include", confidence: 0.86, curation: "human", provenance: true },
  { label: "exclude", confidence: 0.72, curation: "service", provenance: true },
  { label: "exclude", confidence: 0.88, curation: "delegated", provenance: true },
  { label: "exclude", confidence: 0.64, curation: "none", provenance: false },
];

const PREVIEW_CYCLOTRON_ID = "papyrus-relevance";

/**
 * Fixture data for reviewing the cyclotron suggestion UI without a backend:
 * suggestions with provenance on the first references, a mix of human and
 * non-human votes recorded on the References, and a live-agreement payload.
 */
export function createLocalPreviewCyclotronFixtures(references: ReferenceRecord[]): {
  relations: SemanticRelationRecord[];
  /** The first few References with a latest vote recorded on them, by Reference id. */
  votedReferences: Map<string, ReferenceRecord>;
  shadowAgreement: ShadowAgreement;
} {
  const relations: SemanticRelationRecord[] = [];
  const votedReferences = new Map<string, ReferenceRecord>();
  references.slice(0, PREVIEW_SUGGESTION_PLANS.length).forEach((reference, index) => {
    const plan = PREVIEW_SUGGESTION_PLANS[index];
    const lineageId = reference.lineageId ?? reference.id;
    const decidedAt = isoTimestampHoursBeforeBase(40 - index);
    relations.push({
      id: `preview-relevance-relation-${index}`,
      relationState: "current",
      predicate: "relevance_decision_is",
      subjectKind: "reference",
      subjectId: reference.id,
      subjectLineageId: lineageId,
      objectKind: "semanticNode",
      objectId: `semantic-node-relevance-${plan.label}-v1`,
      objectLineageId: `semantic-node-relevance-${plan.label}`,
      subjectStateKey: `reference#${lineageId}#current`,
      objectStateKey: `semanticNode#semantic-node-relevance-${plan.label}#current`,
      objectSubjectStateKey: `semanticNode#semantic-node-relevance-${plan.label}#current#reference`,
      predicateObjectStateKey: `relevance_decision_is#semanticNode#semantic-node-relevance-${plan.label}#current`,
      subjectVersionKey: `reference#${reference.id}`,
      objectVersionKey: `semanticNode#semantic-node-relevance-${plan.label}-v1`,
      confidence: plan.confidence,
      modelVersion: "4",
      reviewRecommended: false,
      metadata: JSON.stringify({
        decisionId: `preview-decision-${index}`,
        label: plan.label,
        probabilities: { include: plan.label === "include" ? plan.confidence : 1 - plan.confidence, exclude: plan.label === "exclude" ? plan.confidence : 1 - plan.confidence },
        version: 4,
        decidedAt,
        labels: ["include", "exclude"],
        positiveLabel: "include",
        question: "Should this source be used as evidence for the publication?",
        cyclotronId: PREVIEW_CYCLOTRON_ID,
        ...(plan.provenance ? {
          provenance: {
            labelSet: ["include", "exclude"],
            doctrineFingerprint: "3f9c2a71d80b46e5",
            teachingFingerprint: "b71e04c9aa5d2f13",
            teachingLabels: 37,
            primingExamples: 6,
          },
        } : {}),
      }),
    } as SemanticRelationRecord);
    if (plan.curation !== "none") {
      // A Reference keeps its latest vote on itself (no Message): the details sit in its curation* fields.
      votedReferences.set(reference.id, {
        ...reference,
        curationStatusUpdatedAt: isoTimestampHoursBeforeBase(30 - index),
        curationStatusUpdatedBy: plan.curation === "delegated" ? "Maya Okafor" : reference.curationStatusUpdatedBy,
        curationActorKind: plan.curation === "service" ? "agent" : "human",
        curationDelegation: plan.curation === "delegated" ? {
          delegationId: "curation-delegation-9b1f6c24",
          relayedBy: "newsroom-reporter",
          instruction: "Reject that one, it duplicates the filing from Tuesday.",
        } : null,
      });
    }
  });
  return {
    relations,
    votedReferences,
    shadowAgreement: {
      schema: SHADOW_AGREEMENT_SCHEMA,
      comparisons: 23,
      agreement: 0.87,
      precision: 0.9,
      recall: 0.82,
      confusion: { truePositive: 9, falsePositive: 1, falseNegative: 2, trueNegative: 11 },
      computedAt: isoTimestampHoursBeforeBase(3),
      positiveLabel: "include",
      loop: { enabled: true, stoppedBecause: "daily decision cap", lastSweepAt: isoTimestampHoursBeforeBase(3), maxDecisionsPerDay: 50 },
    },
  };
}
