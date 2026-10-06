import assert from "node:assert/strict";
import { REBUILD_TRIGGER_ACTIONS, rebuildTriggerSettings } from "../amplify/rebuild-trigger-settings";

const base = { stagingBuildEnabled: false, cmsAppId: "cms1", region: "us-east-1", account: "111122223333" };

const none = rebuildTriggerSettings(base);
assert.deepEqual(none.resources, []);
assert.deepEqual(none.environment, {});

const reader = rebuildTriggerSettings({ ...base, reader: { amplifyAppId: "rdr1" } });
assert.deepEqual(reader.actions, ["amplify:StartJob", "amplify:ListJobs"]);
assert.deepEqual(reader.actions, REBUILD_TRIGGER_ACTIONS);
assert.deepEqual(reader.resources, ["arn:aws:amplify:us-east-1:111122223333:apps/rdr1/branches/main/jobs/*"]);
assert.equal(reader.environment.PAPYRUS_READER_BRANCH, "main");
assert.equal(reader.environment.PAPYRUS_CMS_AMPLIFY_APP_ID, undefined);

const both = rebuildTriggerSettings({
  ...base,
  stagingBuildEnabled: true,
  reader: { amplifyAppId: "rdr1", branchName: "live" },
});
assert.deepEqual(both.resources, [
  "arn:aws:amplify:us-east-1:111122223333:apps/rdr1/branches/live/jobs/*",
  "arn:aws:amplify:us-east-1:111122223333:apps/cms1/branches/staging/jobs/*",
]);
assert.equal(both.environment.PAPYRUS_STAGING_BRANCH, "staging");

const noCmsApp = rebuildTriggerSettings({ ...base, cmsAppId: "", stagingBuildEnabled: true });
assert.deepEqual(noCmsApp.resources, []);

console.log("rebuild trigger settings ok");
