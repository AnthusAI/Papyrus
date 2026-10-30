import assert from "node:assert/strict";
import { referenceVoteFields, validatedCurationSectionId } from "../amplify/functions/shared/reference-curation-metadata";

const enabledSection = { id: "section-research", enabled: true, enabledStatus: "enabled" };
assert.equal(validatedCurationSectionId("section-research", "accept", enabledSection), "section-research");
assert.equal(validatedCurationSectionId("  section-research ", "accept", enabledSection), "section-research");
assert.equal(validatedCurationSectionId(undefined, "accept", null), null);
assert.equal(validatedCurationSectionId("", "reject", null), null);
assert.throws(() => validatedCurationSectionId("section-missing", "accept", null), /was not found/);
assert.throws(() => validatedCurationSectionId("section-research", "accept", { id: "other", enabled: true }), /was not found/);
assert.throws(() => validatedCurationSectionId("section-research", "accept", { ...enabledSection, enabled: false }), /disabled/);
assert.throws(() => validatedCurationSectionId("section-research", "accept", { ...enabledSection, enabledStatus: "disabled" }), /disabled/);
assert.throws(() => validatedCurationSectionId("section-research", "reject", enabledSection), /only when accepting/);

const withSection = referenceVoteFields({ actorKind: "human", sectionId: "section-research" });
assert.equal(withSection.curationSectionId, "section-research");
assert.equal(withSection.curationActorKind, "human");
// A later vote without a Section clears the earlier one: every field is always present.
assert.equal(referenceVoteFields({ actorKind: "human" }).curationSectionId, null);
assert.equal(referenceVoteFields({ actorKind: "human", sectionId: "  " }).curationSectionId, null);

console.log("curation section: ok");
