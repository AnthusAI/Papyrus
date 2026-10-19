import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const NO_CHANGES_REASONS = ["didn't contain changes", "No updates are to be performed"];
const FUNCTION_STILL_ATTACHED_PAUSE_SECONDS = 20;
const FUNCTION_DELETE_ATTEMPTS = 6;

function runAws(awsArguments, { allowFailure = false } = {}) {
  const completed = spawnSync("aws", awsArguments, { encoding: "utf8" });
  if (completed.status !== 0 && !allowFailure) {
    throw new Error(`aws ${awsArguments.slice(0, 2).join(" ")} failed: ${completed.stderr || completed.stdout}`);
  }
  return completed;
}

function runAwsJson(awsArguments) {
  const completed = runAws([...awsArguments, "--output", "json"]);
  return completed.stdout.trim() === "" ? {} : JSON.parse(completed.stdout);
}

function logicalIdsInStack(stackName, region) {
  const completed = runAws(["cloudformation", "list-stack-resources", "--stack-name", stackName, "--region", region, "--output", "json"], { allowFailure: true });
  if (completed.status !== 0) return new Set();
  return new Set(JSON.parse(completed.stdout).StackResourceSummaries.map((summary) => summary.LogicalResourceId));
}

function templateParameterFlags(parameterValues, templateFile) {
  const templateText = fs.readFileSync(templateFile, "utf8");
  const parametersSection = templateText.split("\nResources:")[0].split("\nParameters:\n")[1] ?? "";
  const parameterNames = [...parametersSection.matchAll(/^  ([A-Za-z0-9]+):\s*$/gm)].map((match) => match[1]);
  return parameterNames.map((name) =>
    name in parameterValues
      ? `ParameterKey=${name},ParameterValue=${parameterValues[name]}`
      : `ParameterKey=${name},UsePreviousValue=true`,
  );
}

export function applyChangeSet({ stackName, region, templateFile, parameterValues, adoptions }) {
  const changeSetType = adoptions ? "IMPORT" : "UPDATE";
  const changeSetName = `papyrus-infra-${Date.now()}`;
  const createArguments = [
    "cloudformation", "create-change-set",
    "--stack-name", stackName,
    "--change-set-name", changeSetName,
    "--change-set-type", changeSetType,
    "--template-body", `file://${path.resolve(templateFile)}`,
    "--capabilities", "CAPABILITY_IAM",
    "--region", region,
    "--parameters", ...templateParameterFlags(parameterValues, templateFile),
  ];
  if (adoptions) createArguments.push("--resources-to-import", JSON.stringify(adoptions));
  runAws(createArguments);
  const waiting = runAws(["cloudformation", "wait", "change-set-create-complete", "--stack-name", stackName, "--change-set-name", changeSetName, "--region", region], { allowFailure: true });
  const description = runAwsJson(["cloudformation", "describe-change-set", "--stack-name", stackName, "--change-set-name", changeSetName, "--region", region]);
  if (waiting.status !== 0) {
    const reason = description.StatusReason ?? "";
    runAws(["cloudformation", "delete-change-set", "--stack-name", stackName, "--change-set-name", changeSetName, "--region", region], { allowFailure: true });
    if (NO_CHANGES_REASONS.some((phrase) => reason.includes(phrase))) {
      console.log(`papyrus-infra deploy-edge: ${changeSetType} for ${stackName} has no changes`);
      return false;
    }
    throw new Error(`change set ${changeSetName} failed: ${reason}`);
  }
  console.log(`papyrus-infra deploy-edge: ${changeSetType} ${changeSetName}: ${(description.Changes ?? []).map((change) => `${change.ResourceChange.Action} ${change.ResourceChange.LogicalResourceId}`).join(", ")}`);
  runAws(["cloudformation", "execute-change-set", "--stack-name", stackName, "--change-set-name", changeSetName, "--region", region]);
  const waiter = adoptions ? "stack-import-complete" : "stack-update-complete";
  runAws(["cloudformation", "wait", waiter, "--stack-name", stackName, "--region", region]);
  return true;
}

function sleepSeconds(seconds) {
  spawnSync("sleep", [String(seconds)]);
}

export function deleteOrphanedFunction({ functionName }) {
  const description = runAws(["cloudfront", "describe-function", "--name", functionName, "--output", "json"], { allowFailure: true });
  if (description.status !== 0) {
    console.log(`papyrus-infra deploy-edge: function ${functionName} is already gone`);
    return;
  }
  const entityTag = JSON.parse(description.stdout).ETag;
  for (let attempt = 1; attempt <= FUNCTION_DELETE_ATTEMPTS; attempt += 1) {
    const deletion = runAws(["cloudfront", "delete-function", "--name", functionName, "--if-match", entityTag], { allowFailure: true });
    if (deletion.status === 0) {
      console.log(`papyrus-infra deploy-edge: deleted function ${functionName}`);
      return;
    }
    if (attempt < FUNCTION_DELETE_ATTEMPTS) sleepSeconds(FUNCTION_STILL_ATTACHED_PAUSE_SECONDS);
    else console.warn(`papyrus-infra deploy-edge: could not delete ${functionName} yet, the next build retries: ${deletion.stderr}`);
  }
}

export function deployEdgeStack(options) {
  const { stackName, region, templateFile, parameterValues, adoptionTemplateFile, adoptionResources, orphanedFunctionName } = options;
  const logicalIdsPresent = logicalIdsInStack(stackName, region);
  const pendingAdoptions = (adoptionResources ?? []).filter((resource) => !logicalIdsPresent.has(resource.LogicalResourceId));
  if (pendingAdoptions.length > 0) {
    if (!adoptionTemplateFile) throw new Error("resources need adopting but no --adoption-template was given");
    applyChangeSet({ stackName, region, templateFile: adoptionTemplateFile, parameterValues, adoptions: pendingAdoptions });
  }
  applyChangeSet({ stackName, region, templateFile, parameterValues, adoptions: undefined });
  if (orphanedFunctionName) deleteOrphanedFunction({ functionName: orphanedFunctionName });
}
