import assert from "node:assert/strict";
import test from "node:test";
import { FIXTURE_PROFILE } from "./fixtures/visual-style-fixture";
import {
  addTypeDocument, describeSource, effectiveUse, imageTypeRows, keyFromLabel, moveSource, pictureProblem, retireDocument, safeZoneBox, unusedSources,
} from "../lib/images/visual-style-admin";

test("a type's row says what it is in plain terms, including what it inherits", () => {
  const rows = Object.fromEntries(imageTypeRows(FIXTURE_PROFILE).map((row) => [row.key, row]));
  assert.equal(rows["cover-illustration"].family, "Editorial illustration");
  assert.deepEqual([rows["cover-illustration"].use, rows["cover-illustration"].thumbnail, rows["cover-illustration"].smallestWidthPx, rows["cover-illustration"].exampleCount], ["cover", true, 160, 3]);
  assert.deepEqual(rows["inline-illustration"].sources, ["generated", "stock"]);
  assert.deepEqual([rows["inline-illustration"].use, rows["inline-illustration"].thumbnail, rows["inline-illustration"].inheritsFrom, rows["inline-illustration"].exampleCount], ["inline", false, "Headline illustration", 0]);
  assert.equal(rows["social-card"].sources.join(), "stock,generated", "a child type with no sources of its own shows its parent's");
  assert.equal(effectiveUse(FIXTURE_PROFILE, "social-card"), "social");
});

test("adding a type: a key from the name, never a duplicate, and Start from sets extends without copying examples", () => {
  assert.equal(keyFromLabel("  Newsletter picture! "), "newsletter-picture");
  const blank = addTypeDocument(FIXTURE_PROFILE, { label: "Newsletter picture", description: "Top of the newsletter.", startFrom: null, use: "cover" });
  assert.deepEqual(blank.document, { imageTypes: { "newsletter-picture": { label: "Newsletter picture", description: "Top of the newsletter.", use: "cover", sources: ["stock", "generated"] } } });
  const child = addTypeDocument(FIXTURE_PROFILE, { label: "Wide cover", description: "", startFrom: "cover-illustration", use: "cover" });
  assert.deepEqual(child.document?.imageTypes["wide-cover"], { label: "Wide cover", description: "", extends: "cover-illustration" });
  assert.equal("examples" in (child.document?.imageTypes["wide-cover"] ?? {}), false);
  assert.equal(addTypeDocument(FIXTURE_PROFILE, { label: "Wide cover", description: "", startFrom: "cover-illustration", use: "inline" }).document?.imageTypes["wide-cover"].use, "inline");
  assert.match(addTypeDocument(FIXTURE_PROFILE, { label: "Social card", description: "", startFrom: null, use: "social" }).problem ?? "", /already a type called Social card/);
  assert.match(addTypeDocument(FIXTURE_PROFILE, { label: "  ", description: "", startFrom: null, use: "cover" }).problem ?? "", /Give the type a name/);
  assert.match(addTypeDocument(FIXTURE_PROFILE, { label: "!!!", description: "", startFrom: null, use: "cover" }).problem ?? "", /at least one letter or number/);
  assert.match(addTypeDocument(FIXTURE_PROFILE, { label: "X", description: "", startFrom: "nope", use: "cover" }).problem ?? "", /not in this profile/);
});

test("retiring changes one flag and never removes a type", () => {
  assert.deepEqual(retireDocument("cover-photo", true), { imageTypes: { "cover-photo": { retired: true } } });
});

test("sources move one place and stay a list of the three known sources", () => {
  assert.deepEqual(moveSource(["stock", "generated"], 1, -1), ["generated", "stock"]);
  assert.deepEqual(moveSource(["stock", "generated"], 0, -1), ["stock", "generated"]);
  assert.deepEqual(moveSource(["stock", "generated"], 1, 1), ["stock", "generated"]);
  assert.deepEqual(unusedSources(["stock"]), ["figure-system", "generated"]);
});

test("a picture that cannot be an example is refused in words before anything is uploaded", () => {
  assert.equal(pictureProblem({ name: "a.png", type: "image/png", size: 1000 }), null);
  assert.equal(pictureProblem({ name: "a.webp", type: "image/webp", size: 10 * 1024 * 1024 }), null);
  assert.match(pictureProblem({ name: "a.svg", type: "image/svg+xml", size: 10 }) ?? "", /not a PNG, JPEG or WebP/);
  assert.match(pictureProblem({ name: "big.jpg", type: "image/jpeg", size: 10 * 1024 * 1024 + 1 }) ?? "", /10 MB or smaller/);
});

test("where a rule came from is said in words", () => {
  assert.equal(describeSource("publication", FIXTURE_PROFILE, "inline-illustration"), "Brand");
  assert.equal(describeSource("treatment:editorial-illustration", FIXTURE_PROFILE, "x"), "Family: Editorial illustration");
  assert.equal(describeSource("image-type:cover-illustration", FIXTURE_PROFILE, "inline-illustration"), "Parent type: Headline illustration");
  assert.equal(describeSource("image-type:inline-illustration", FIXTURE_PROFILE, "inline-illustration"), "This type");
  assert.equal(describeSource("use:inline", FIXTURE_PROFILE, "x"), "Use: In the article");
});

test("a safe zone is placed on the sample frame only when its words say where", () => {
  assert.deepEqual(safeZoneBox("upper third"), { top: 0, left: 0, width: 100, height: 33.3 });
  assert.equal(safeZoneBox("outer edge"), null);
});
