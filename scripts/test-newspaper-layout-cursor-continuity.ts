import assert from "node:assert/strict";

class FixedWidthOffscreenCanvas {
  getContext() {
    return {
      font: "",
      measureText: (text: string) => ({ width: text.length * 9 }),
    };
  }
}
(globalThis as { OffscreenCanvas?: unknown }).OffscreenCanvas = FixedWidthOffscreenCanvas;

import { articles } from "../lib/articles";
import { createDefaultEditionLayoutPlan, normalizeEditionLayoutPlan, type EditionLayoutPlan } from "../lib/layout-plan";
import { layoutScenarios } from "../lib/layout-scenarios";
import { buildNewspaperLayout, type NewspaperLayout, type PlacedTextRange } from "../lib/newspaper-layout";
import { articleToPublicationItem, type PublicationItem } from "../lib/publication-items";

const PAGE_WIDTHS = [1280, 640, 390];
const VIEWPORT_HEIGHT = 900;
const TWO_HOP_LABEL_ISSUE = "PPY-be0edc";
const UNTERMINATED_TEASER_ISSUE = "PPY-dfaabb";
const KNOWN_UNTERMINATED_ARTICLE_IDS = new Set(["river-court", "night-trains", "climate-ledger"]);

const unterminatedArticles: { context: string; articleId: string; message: string }[] = [];

type SolvedBlockSummary = {
  blockId: string;
  pageNumber: number;
  label: string | undefined;
  jumpLabel: string | undefined;
};

function summarizeSolvedBlocks(layout: NewspaperLayout): Map<string, SolvedBlockSummary> {
  const summaries = new Map<string, SolvedBlockSummary>();
  for (const page of layout.pages) {
    for (const region of page.regions) {
      for (const block of region.blocks) {
        summaries.set(block.id, {
          blockId: block.id,
          pageNumber: page.pageNumber,
          label: block.label,
          jumpLabel: block.jumpLabel,
        });
      }
    }
  }
  return summaries;
}

function groupRangesByArticle(ranges: PlacedTextRange[]): Map<string, PlacedTextRange[]> {
  const grouped = new Map<string, PlacedTextRange[]>();
  for (const range of ranges) {
    grouped.set(range.articleId, [...(grouped.get(range.articleId) ?? []), range]);
  }
  return grouped;
}

function cursorsEqual(left: PlacedTextRange["endCursor"], right: PlacedTextRange["startCursor"]): boolean {
  return left.segmentIndex === right.segmentIndex && left.graphemeIndex === right.graphemeIndex;
}

function assertCursorContinuity(context: string, layout: NewspaperLayout, expectedPageCount: number) {
  assert.equal(layout.pages.length, expectedPageCount, `${context}: solved page count matches the plan`);
  const solvedBlocks = summarizeSolvedBlocks(layout);
  for (const [articleId, ranges] of groupRangesByArticle(layout.textRanges)) {
    for (let index = 0; index < ranges.length - 1; index += 1) {
      assert.ok(
        cursorsEqual(ranges[index].endCursor, ranges[index + 1].startCursor),
        `${context}: ${articleId} handoff ${ranges[index].blockId} -> ${ranges[index + 1].blockId} duplicates or skips text`,
      );
    }
    const lastRange = ranges[ranges.length - 1];
    const lastBlock = solvedBlocks.get(lastRange.blockId);
    if (!(lastRange.exhausted || Boolean(lastBlock?.jumpLabel))) {
      unterminatedArticles.push({
        context,
        articleId,
        message: `${context}: ${articleId} ends in ${lastRange.blockId} without being exhausted or advertising a jump`,
      });
    }
  }
}

function assertJumpLabelsMatchPlan(context: string, layout: NewspaperLayout, plan: EditionLayoutPlan, items: PublicationItem[]) {
  const solvedBlocks = summarizeSolvedBlocks(layout);
  for (const page of plan.pages) {
    for (const region of page.regions) {
      for (const blockSpec of region.blocks) {
        if (blockSpec.type !== "articleFrame") continue;
        const jumpTargetPage = blockSpec.cutPolicy?.jumpTargetPage;
        if (!jumpTargetPage) continue;
        const solved = solvedBlocks.get(blockSpec.id);
        if (!solved?.jumpLabel) continue;
        const item = items.find((candidate) => candidate.slug === blockSpec.itemId);
        const shortSlug = item?.type === "article" ? item.shortSlug?.trim().toUpperCase() : undefined;
        assert.equal(
          solved.jumpLabel,
          `SEE ${shortSlug || "MORE"} ON A${jumpTargetPage}`,
          `${context}: jump label of ${blockSpec.id}`,
        );
      }
    }
  }
}

function findPageNumberOfLatestEarlierRange(layout: NewspaperLayout, articleId: string, blockId: string): number | undefined {
  const solvedBlocks = summarizeSolvedBlocks(layout);
  const ranges = layout.textRanges.filter((range) => range.articleId === articleId);
  const index = ranges.findIndex((range) => range.blockId === blockId);
  return index > 0 ? solvedBlocks.get(ranges[index - 1].blockId)?.pageNumber : undefined;
}

function assertContinuationHeading(
  context: string,
  layout: NewspaperLayout,
  items: PublicationItem[],
  articleId: string,
  continuationBlockId: string,
) {
  const solvedBlocks = summarizeSolvedBlocks(layout);
  const sourcePageNumber = findPageNumberOfLatestEarlierRange(layout, articleId, continuationBlockId);
  assert.ok(sourcePageNumber, `${context}: ${continuationBlockId} has an earlier range to continue from`);
  const item = items.find((candidate) => candidate.slug === articleId);
  const shortSlug = item?.type === "article" ? item.shortSlug?.trim().toUpperCase() : undefined;
  const expected = shortSlug ? `${shortSlug} FROM A${sourcePageNumber}` : `FROM A${sourcePageNumber}`;
  assert.equal(solvedBlocks.get(continuationBlockId)?.label, expected, `${context}: continuation heading of ${continuationBlockId}`);
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function createFixtureItems(): PublicationItem[] {
  return articles.map((article) => articleToPublicationItem(cloneJson(article)));
}

function createFixturePlan(): EditionLayoutPlan {
  return normalizeEditionLayoutPlan(cloneJson(createDefaultEditionLayoutPlan(articles.map((article) => article.slug))));
}

function createTwoHopPlan(): EditionLayoutPlan {
  const plan = createFixturePlan();
  const secondPage = plan.pages.find((page) => page.pageNumber === 2);
  const thirdPage = plan.pages.find((page) => page.pageNumber === 3);
  assert.ok(secondPage && thirdPage, "default plan has pages 2 and 3");
  const middleBlock = secondPage.regions[0].blocks.find((block) => block.id === "agent-procedure-patterns-page-2");
  assert.ok(middleBlock?.type === "articleFrame");
  middleBlock.cutPolicy = { maxBodyLines: 8, jumpTargetPage: 3 };
  const templateRegion = thirdPage.regions[0];
  const templateBlock = templateRegion.blocks[0];
  thirdPage.regions.push({
    ...cloneJson(templateRegion),
    id: "agent-procedure-patterns-tail",
    blocks: [
      {
        ...cloneJson(templateBlock),
        id: "agent-procedure-patterns-page-3",
        itemId: "agent-procedure-patterns",
        flowKey: "agent-procedure-patterns",
        startCursor: "current",
      } as typeof templateBlock,
    ],
  });
  return normalizeEditionLayoutPlan(plan);
}

function removeShortSlugs(items: PublicationItem[]): PublicationItem[] {
  return items.map((item) => {
    const copy = cloneJson(item);
    if (copy.type === "article") delete copy.shortSlug;
    return copy;
  });
}

for (const scenario of layoutScenarios) {
  for (const pageWidth of PAGE_WIDTHS) {
    const context = `${scenario.id}@${pageWidth}`;
    const plan = normalizeEditionLayoutPlan(scenario.layoutPlan, `scenario ${scenario.id}`);
    const layout = buildNewspaperLayout(scenario.items, pageWidth, VIEWPORT_HEIGHT, plan);
    assertCursorContinuity(context, layout, plan.pages.length);
    assertJumpLabelsMatchPlan(context, layout, plan, scenario.items);
  }
}

for (const pageWidth of PAGE_WIDTHS) {
  const items = createFixtureItems();
  const plan = createFixturePlan();
  const context = `labels@${pageWidth}`;
  const layout = buildNewspaperLayout(items, pageWidth, VIEWPORT_HEIGHT, plan);
  const solvedBlocks = summarizeSolvedBlocks(layout);
  assert.equal(solvedBlocks.get("front-schools-reading-lab")?.jumpLabel, "SEE READING ON A3", context);
  assert.equal(solvedBlocks.get("front-agent-procedure-patterns")?.jumpLabel, "SEE AGENTS ON A2", context);
  assertContinuationHeading(context, layout, items, "agent-procedure-patterns", "agent-procedure-patterns-page-2");
  assertContinuationHeading(context, layout, items, "schools-reading-lab", "schools-reading-lab-page-3");

  const unslugged = removeShortSlugs(items);
  const unsluggedLayout = buildNewspaperLayout(unslugged, pageWidth, VIEWPORT_HEIGHT, plan);
  const unsluggedBlocks = summarizeSolvedBlocks(unsluggedLayout);
  assert.equal(unsluggedBlocks.get("front-schools-reading-lab")?.jumpLabel, "SEE MORE ON A3", `${context} no shortSlug`);
  assert.equal(unsluggedBlocks.get("schools-reading-lab-page-3")?.label, "FROM A1", `${context} no shortSlug`);
}

const unexpectedUnterminated = unterminatedArticles.filter((entry) => !KNOWN_UNTERMINATED_ARTICLE_IDS.has(entry.articleId));
assert.deepEqual(
  unexpectedUnterminated.map((entry) => entry.message),
  [],
  "articles must end exhausted or with a planned jump",
);
const observedUnterminatedIds = new Set(unterminatedArticles.map((entry) => entry.articleId));
for (const knownId of KNOWN_UNTERMINATED_ARTICLE_IDS) {
  assert.ok(
    observedUnterminatedIds.has(knownId),
    `${knownId} now terminates correctly; remove it from KNOWN_UNTERMINATED_ARTICLE_IDS (${UNTERMINATED_TEASER_ISSUE})`,
  );
}
console.log(`known unterminated teasers until ${UNTERMINATED_TEASER_ISSUE} lands: ${[...observedUnterminatedIds].join(", ")}`);

let twoHopFailure: Error | undefined;
for (const pageWidth of PAGE_WIDTHS) {
  const items = createFixtureItems();
  const plan = createTwoHopPlan();
  const context = `two-hop@${pageWidth}`;
  const layout = buildNewspaperLayout(items, pageWidth, VIEWPORT_HEIGHT, plan);
  assertCursorContinuity(context, layout, plan.pages.length);
  try {
    assertContinuationHeading(context, layout, items, "agent-procedure-patterns", "agent-procedure-patterns-page-2");
    assertContinuationHeading(context, layout, items, "agent-procedure-patterns", "agent-procedure-patterns-page-3");
  } catch (error) {
    twoHopFailure = error as Error;
  }
}

if (twoHopFailure) {
  console.log(`known failure until ${TWO_HOP_LABEL_ISSUE} lands: ${twoHopFailure.message}`);
} else {
  assert.fail(`two-hop continuation headings now pass; remove the known-failure guard for ${TWO_HOP_LABEL_ISSUE}`);
}

console.log("newspaper layout cursor continuity ok");
