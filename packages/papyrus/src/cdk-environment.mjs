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

export function resolveCdkAccount({ explicitAccount, environment = process.env, lookupCallerAccount = callerAccountFromAwsCli }) {
  if (explicitAccount) return explicitAccount;
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
