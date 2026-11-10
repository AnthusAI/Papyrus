import assert from "node:assert/strict";
import type { NewsroomSectionRecord } from "../lib/category-repository";
import { newsroomDeskPickerOptions } from "../lib/newsroom-sections";

const section = (id: string, title: string, sortOrder: number, enabled = true): NewsroomSectionRecord => (
  { id, title, shortTitle: title, type: "canonical", editorialMission: "", editorialPolicy: "", enabled, enabledStatus: enabled ? "enabled" : "disabled", sortOrder } as NewsroomSectionRecord
);
const sections = [section("security", "Security", 2), section("methods", "Methods", 1), section("retired", "Retired", 3, false)];
const scenario = process.argv[2] ?? "all";
const runs: Record<string, () => void> = {
  lists_sections() {
    assert.deepEqual(newsroomDeskPickerOptions(sections, "").map(option => option.value), ["methods", "security"], "the enabled sections, in the site's order, are what the picker offers");
  },
  shows_current() {
    const options = newsroomDeskPickerOptions(sections, "security");
    assert.equal(options.find(option => option.value === "security")?.label, "Security", "the Story's own section is in the list under its title");
    assert.equal(options.length, 2, "nothing is added when the list already holds the value");
  },
  keeps_unlisted_current() {
    assert.deepEqual(newsroomDeskPickerOptions([], "security").map(option => [option.value, option.label]), [["security", "Security"]], "with no list loaded the picker still shows the Story's own section, not 'No section'");
    assert.ok(newsroomDeskPickerOptions(sections, "retired").some(option => option.value === "retired" && option.label === "Retired"), "a disabled section the Story still has stays visible");
  },
};
for (const [name, run] of Object.entries(runs)) if (scenario === "all" || scenario === name) run();
console.log("newsroom section picker ok");
