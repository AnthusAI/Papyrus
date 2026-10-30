/**
 * A rejection's written reason, read for the policy reason code it names.
 *
 * The editor gives words, not a chip. The curation Lambda reads those words so
 * the two scope-training negatives keep arriving, and files words that name no
 * code under "other" rather than guessing one the sentence cannot support.
 */
import assert from "node:assert/strict";
import {
  isScopeTrainingNegativeReason,
  rejectionReasonCodeForWrittenReason,
  type ReferenceRejectionReasonCode,
} from "../lib/reference-policy";

const read = (words: unknown) => rejectionReasonCodeForWrittenReason(words);
const negative = (words: string) => {
  const code = read(words);
  return Boolean(code && isScopeTrainingNegativeReason(code));
};

// Words that plainly say the source is out of scope teach the classifier again.
for (const words of [
  "Out of scope for this publication.",
  "This sits outside our beat.",
  "Not in our scope — it is a consumer gadget review.",
  "Off-topic: the piece is about municipal bonds.",
  "The source has nothing to do with what we cover.",
  "Not relevant to the desk.",
  "Irrelevant.",
  "Wrong subject entirely.",
]) {
  assert.equal(read(words), "out_of_scope", `out of scope: ${words}`);
  assert.ok(negative(words), `a scope negative reaches the classifier: ${words}`);
}

// So do words that say a policy excludes it.
for (const words of [
  "Excluded by our policy on vendor blogs.",
  "Against policy.",
  "Our editorial policy rules this kind of source out.",
  "Policy forbids citing anonymous leak sites.",
  "We don't cover press releases.",
  "Prohibited source.",
  "The domain is on the blocklist.",
]) {
  assert.equal(read(words), "policy_exclusion", `policy exclusion: ${words}`);
  assert.ok(negative(words), `a policy negative reaches the classifier: ${words}`);
}

// The bookkeeping codes are read too, so the editor's words are not flattened.
assert.equal(read("Duplicate of the Reuters wire piece."), "duplicate");
assert.equal(read("We already have this one."), "duplicate");
assert.equal(read("Behind a paywall, so there is nothing to read."), "unavailable");
assert.equal(read("Dead link — the page is gone."), "unavailable");
assert.equal(read("Cannot verify who wrote this."), "provenance");
assert.equal(read("No byline and no citations."), "provenance");
assert.equal(read("Low quality: SEO filler."), "low_quality");
assert.equal(read("Poorly sourced throughout."), "low_quality");

/**
 * A sentence that names a mechanical reason as well as scope is filed under the
 * mechanical one. A false scope negative teaches the classifier something
 * wrong; a missed one only leaves it untaught, so the scope codes are read last.
 */
for (const [words, code] of [
  ["Already have it, and it is off our beat anyway.", "duplicate"],
  ["Paywalled, and out of scope besides.", "unavailable"],
  ["No byline, and unrelated to the desk.", "provenance"],
  ["Low quality and off-topic.", "low_quality"],
] as Array<[string, ReferenceRejectionReasonCode]>) {
  assert.equal(read(words), code, `the mechanical reason wins: ${words}`);
  assert.ok(!negative(words), `no scope negative is invented from: ${words}`);
}

// Words that name no code are filed under "other": honest, and never a training negative.
for (const words of [
  "Not for us.",
  "The editor and I talked about this one and decided against it.",
  "No.",
  "Maybe later in the cycle.",
]) {
  assert.equal(read(words), "other", `no code to read: ${words}`);
  assert.ok(!negative(words), `"other" teaches the classifier nothing: ${words}`);
}

// Blank words are no reason at all, so the caller refuses the rejection.
for (const words of ["", "   ", "\n\t ", null, undefined]) {
  assert.equal(read(words), null, `blank words yield no code: ${JSON.stringify(words)}`);
}

// Punctuation, case and curly apostrophes do not hide a phrase.
assert.equal(read("OUT-OF-SCOPE!"), "out_of_scope");
assert.equal(read("We don’t publish this kind of thing."), "policy_exclusion");
assert.equal(read("(duplicate)"), "duplicate");

// A whole word only: a phrase is never read out of the middle of another word.
assert.equal(read("The slopes of the funding curve are the story here."), "other", "\"slop\" is not read out of \"slopes\"");

console.log("reference reason code: written reasons yield policy codes, mechanical reasons win over scope, and vague words stay \"other\"");
