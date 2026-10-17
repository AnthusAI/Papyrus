/**
 * Environment and IAM policy for the content-actions Lambda's site triggers.
 * Pure (no CDK imports) so the policy can be tested without synthesizing.
 */
export type RebuildTriggerInput = {
  reader?: { amplifyAppId: string; branchName?: string };
  stagingBuildEnabled: boolean;
  cmsAppId: string;
  region: string;
  account: string;
};

export type RebuildTriggerSettings = {
  environment: Record<string, string>;
  actions: string[];
  resources: string[];
};

export const REBUILD_TRIGGER_ACTIONS = ["amplify:StartJob", "amplify:ListJobs"];

function branchJobsArn(input: RebuildTriggerInput, appId: string, branch: string): string {
  return `arn:aws:amplify:${input.region}:${input.account}:apps/${appId}/branches/${branch}/jobs/*`;
}

export function rebuildTriggerSettings(input: RebuildTriggerInput): RebuildTriggerSettings {
  const environment: Record<string, string> = {};
  const resources: string[] = [];
  const readerAppId = (input.reader?.amplifyAppId ?? "").trim();
  if (readerAppId !== "") {
    const readerBranch = (input.reader?.branchName ?? "").trim() || "main";
    environment.PAPYRUS_READER_AMPLIFY_APP_ID = readerAppId;
    environment.PAPYRUS_READER_BRANCH = readerBranch;
    resources.push(branchJobsArn(input, readerAppId, readerBranch));
  }
  const cmsAppId = input.cmsAppId.trim();
  if (input.stagingBuildEnabled && cmsAppId !== "") {
    environment.PAPYRUS_CMS_AMPLIFY_APP_ID = cmsAppId;
    environment.PAPYRUS_STAGING_BRANCH = "staging";
    resources.push(branchJobsArn(input, cmsAppId, "staging"));
  }
  return { environment, actions: REBUILD_TRIGGER_ACTIONS, resources };
}
