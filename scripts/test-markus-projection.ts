/**
 * Exercises `projectMarkusJsonToPretext` (lib/markus-projection.ts) against
 * a real `markus ast` capture (scripts/fixtures/markus-sample.ast.json,
 * generated from scripts/fixtures/markus-sample.md by the actual Markus
 * CLI -- not hand-invented JSON). Run with:
 *
 *   npx tsx scripts/test-markus-projection.ts
 *
 * The fixture exercises pull-quote, card-grid/card, two-up/column,
 * heading, paragraph, an inline code_span vs. a block code, and figure --
 * the same directive mix PPY-a10206 / PPY-88f77b's acceptance criteria
 * require a sample article to cover.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { articles } from "../lib/articles";
import { MarkusSchemaVersionError, parseMarkusDocument } from "../lib/markus-ir";
import { projectMarkusDocumentToPretext, projectMarkusJsonToPretext } from "../lib/markus-projection";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

function assertEqual<T>(actual: T, expected: T, message: string) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  assert(a === e, `${message}\n  expected: ${e}\n  actual:   ${a}`);
}

const fixturePath = path.join(__dirname, "fixtures", "markus-sample.ast.json");
const raw = JSON.parse(readFileSync(fixturePath, "utf8"));

const projection = projectMarkusJsonToPretext(raw);

assertEqual(
  projection.pullQuotes,
  ["The practical breakthrough is not giving agents a bigger sandbox."],
  "pull-quote should be extracted into pullQuotes, not body",
);

assertEqual(
  projection.images,
  [
    {
      id: "figure-0",
      type: "image",
      src: "diagram.png",
      alt: "State diagram",
      caption: "Two states, one agent",
      credit: "",
    },
  ],
  "figure directive should project to an ArticleImageAsset",
);

assert(projection.body.includes("Developers are learning that reliable agents need less freedom, not more."), "first paragraph missing from body");
assert(projection.body.includes("Across demos and tool launches, builders kept circling the same answer."), "second paragraph missing from body");
assert(projection.body.includes("Planning state"), "heading text missing from body");
assert(
  projection.body.some((line) => line.includes("Read-only tools.") && line.includes("code_span") && line.includes("should not be confused with a block")),
  "paragraph with inline code_span should flatten to plain text in body, code_span distinct from block code",
);
assert(
  projection.body.some((line) => line.includes('def plan():')),
  "block code should be preserved (degraded) into body, not dropped",
);
assert(projection.body.includes("Look before you leap."), "card-grid > card content should degrade into body");
assert(projection.body.includes("Only after planning."), "second card content should degrade into body");
assert(projection.body.includes("Planning state keeps risk low."), "two-up > column content should degrade into body");
assert(projection.body.includes("Implementation state is where damage happens."), "second column content should degrade into body");
assert(projection.body.includes("The lesson is not that agents are over."), "trailing paragraph missing from body");

assert(!projection.body.some((line) => line === "The practical breakthrough is not giving agents a bigger sandbox."), "pull-quote text must not ALSO leak into body");

// Nothing dropped: every body entry is non-empty, and pullQuotes/images are
// disjoint from body (checked above via exact array equality).
for (const line of projection.body) {
  assert(line.trim().length > 0, "body should never contain a blank/whitespace-only entry");
}

// schema_version boundary check: must fail loudly, not silently coerce.
try {
  parseMarkusDocument({ ...raw, schema_version: 999 });
  throw new Error("FAIL: expected MarkusSchemaVersionError for schema_version mismatch");
} catch (error) {
  assert(error instanceof MarkusSchemaVersionError, `expected MarkusSchemaVersionError, got ${error}`);
}

// Sanity: projectMarkusDocumentToPretext (pre-parsed) agrees with the JSON
// entry point.
const reparsed = parseMarkusDocument(raw);
assertEqual(projectMarkusDocumentToPretext(reparsed), projection, "parsed vs. JSON entry points should agree");

// Round-trip regression: a seed article migrated to Markus Markdown must
// project back to the same body: string[] and pullQuotes[] it has today
// (acceptance proof for PPY-b794e1).
const seedArticle = articles.find((article) => article.slug === "agent-procedure-patterns");
assert(seedArticle, "seed article agent-procedure-patterns must exist in lib/articles.ts");
const roundTripPath = path.join(__dirname, "fixtures", "agent-procedure-patterns.ast.json");
const roundTripRaw = JSON.parse(readFileSync(roundTripPath, "utf8"));
const roundTripProjection = projectMarkusJsonToPretext(roundTripRaw);
assertEqual(roundTripProjection.body, seedArticle.body, "migrated seed article body must round-trip");
assertEqual(roundTripProjection.pullQuotes, seedArticle.pullQuotes, "migrated seed article pullQuotes must round-trip");
for (const quote of roundTripProjection.pullQuotes ?? []) {
  assert(
    !roundTripProjection.body.some((line) => line === quote),
    "pull-quote text must not also appear as a standalone body line",
  );
}

console.log("Markus -> Pretext projection tests passed.");
