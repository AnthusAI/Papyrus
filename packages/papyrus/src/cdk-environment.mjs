import { spawnSync } from "node:child_process";

const DEFAULT_REGION = "us-east-1";

export function resolveCdkRegion({ explicitRegion, environment = process.env }) {
  return (
    explicitRegion ||
    environment.AWS_REGION ||
    environment.AWS_DEFAULT_REGION ||
    environment.CDK_DEFAULT_REGION ||
    DEFAULT_REGION
  );
}

function callerAccountFromAwsCli() {
  const completed = spawnSync("aws", ["sts", "get-caller-identity", "--output", "json"], { encoding: "utf8" });
  if (completed.error) throw new Error(`could not run the aws CLI: ${completed.error.message}`);
  if (completed.status !== 0) throw new Error(String(completed.stderr || completed.stdout).trim() || `aws exited with status ${completed.status}`);
  return JSON.parse(completed.stdout).Account;
}

/** Names the account a deploy is meant for, so no site file has to carry it. Wins over CDK_DEFAULT_ACCOUNT and the caller's STS account. */
export const PINNED_ACCOUNT_VARIABLE = "PAPYRUS_AWS_ACCOUNT_ID";

export function pinnedAccountFromEnvironment(environment = process.env) {
  const pinned = String(environment[PINNED_ACCOUNT_VARIABLE] ?? "").trim();
  if (!pinned) return undefined;
  if (!/^\d{12}$/.test(pinned)) throw new Error(`${PINNED_ACCOUNT_VARIABLE} must be a 12-digit AWS account id`);
  return pinned;
}

/**
 * Fails when the credentials in use belong to another account than the one the deploy was pinned to, so a
 * mis-set pin or the wrong profile can never deploy into the wrong account. A no-op without a pin.
 */
export function assertCallerMatchesPinnedAccount({ environment = process.env, lookupCallerAccount = callerAccountFromAwsCli } = {}) {
  const pinned = pinnedAccountFromEnvironment(environment);
  if (!pinned) return;
  let caller;
  try {
    caller = String(lookupCallerAccount());
  } catch (error) {
    throw new Error(`${PINNED_ACCOUNT_VARIABLE} is set but the caller's account cannot be checked: ${error instanceof Error ? error.message : error}`);
  }
  if (caller !== pinned) {
    throw new Error(`wrong AWS account: the credentials are for ${caller} but ${PINNED_ACCOUNT_VARIABLE} pins this deploy to ${pinned}; nothing was deployed`);
  }
}

export function resolveCdkAccount({ explicitAccount, environment = process.env, lookupCallerAccount = callerAccountFromAwsCli }) {
  if (explicitAccount) return explicitAccount;
  const pinned = pinnedAccountFromEnvironment(environment);
  if (pinned) return pinned;
  if (environment.CDK_DEFAULT_ACCOUNT) return environment.CDK_DEFAULT_ACCOUNT;
  let account;
  try {
    account = lookupCallerAccount();
  } catch (error) {
    throw new Error(
      `cannot determine the AWS account: pass --account, set CDK_DEFAULT_ACCOUNT, or provide credentials for "aws sts get-caller-identity" (${error instanceof Error ? error.message : error})`,
    );
  }
  if (!/^\d{12}$/.test(String(account))) {
    throw new Error(`cannot determine the AWS account: "aws sts get-caller-identity" returned ${JSON.stringify(account)}; pass --account or set CDK_DEFAULT_ACCOUNT`);
  }
  return String(account);
}

export function resolveCdkEnvironment({ explicitAccount, explicitRegion, environment = process.env, lookupCallerAccount }) {
  return {
    account: resolveCdkAccount({ explicitAccount, environment, lookupCallerAccount }),
    region: resolveCdkRegion({ explicitRegion, environment }),
  };
}
