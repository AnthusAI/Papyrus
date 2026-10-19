import assert from "node:assert/strict";
import { referenceCurationMetadata, validatedCurationSectionId } from "../amplify/functions/shared/reference-curation-metadata";

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

const base = { action: "accept", curationStatus: "accepted", reasonCode: null, referenceId: "r-v1", referenceLineageId: "r" };
const withSection = referenceCurationMetadata({ ...base, actorKind: "human", sectionId: "section-research" });
assert.equal(withSection.sectionId, "section-research");
assert.equal(withSection.actorKind, "human");
assert.equal("sectionId" in referenceCurationMetadata({ ...base, actorKind: "human" }), false);
assert.equal("sectionId" in referenceCurationMetadata({ ...base, sectionId: null }), false);

console.log("curation section: ok");
