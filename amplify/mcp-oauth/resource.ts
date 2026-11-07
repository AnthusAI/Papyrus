import { AssetHashType, Duration, RemovalPolicy, Stack } from "aws-cdk-lib";
import { AttributeType, BillingMode, Table, TableEncryption } from "aws-cdk-lib/aws-dynamodb";
import { ArnPrincipal, Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Key } from "aws-cdk-lib/aws-kms";
import { Architecture, Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { execFileSync } from "node:child_process";
import { copyFileSync } from "node:fs";
import path from "node:path";
import { packageRoot } from "../functions/shared/python-bundle";

export type McpOAuthPlan = { origin: string; invokerRoleArn: string };

/** Refuse partial configuration; never infer an issuer from a request Host. */
export function planMcpOAuth(enabled: boolean, env: Record<string, string | undefined>): McpOAuthPlan | undefined {
  if (!enabled) return undefined;
  const origin = (env.PAPYRUS_CONSOLE_ORIGIN ?? env.PAPYRUS_SITE_ORIGIN ?? "").trim();
  let parsed: URL;
  try { parsed = new URL(origin); } catch { throw new Error("MCP needs a configured HTTPS console origin"); }
  if (parsed.protocol !== "https:" || parsed.origin !== origin) throw new Error("MCP needs a plain HTTPS console origin");
  const invokerRoleArn = (env.PAPYRUS_MCP_INVOKER_ROLE_ARN ?? "").trim();
  if (!/^arn:aws[a-z-]*:iam::\d{12}:role\/.+$/.test(invokerRoleArn)) throw new Error("MCP needs PAPYRUS_MCP_INVOKER_ROLE_ARN");
  return { origin, invokerRoleArn };
}

/** The KMS data key and AES-GCM implementation are scoped to this site's grant store. */
export function addMcpOAuth(stack: Stack, plan: McpOAuthPlan, bundledCode?: Code): { functionArn: string; origin: string } {
  const table = new Table(stack, "Grants", { partitionKey: { name: "pk", type: AttributeType.STRING },
    billingMode: BillingMode.PAY_PER_REQUEST, timeToLiveAttribute: "expiresAt", encryption: TableEncryption.AWS_MANAGED,
    removalPolicy: RemovalPolicy.RETAIN });
  const key = new Key(stack, "GrantKey", { enableKeyRotation: true, removalPolicy: RemovalPolicy.RETAIN });
  const functionDir = path.join(packageRoot, "amplify/functions/mcp-oauth");
  const code = bundledCode ?? Code.fromAsset(functionDir, { assetHashType: AssetHashType.OUTPUT, bundling: {
    image: Runtime.PYTHON_3_12.bundlingImage,
    local: { tryBundle(outputDir: string) {
      const extra = (process.env.PAPYRUS_PIP_EXTRA_ARGS ?? "").trim().split(/\s+/).filter(Boolean);
      execFileSync((process.env.PAPYRUS_PIP_PYTHON ?? "python3").trim(), ["-m", "pip", "install", "--target", outputDir,
        "--no-cache-dir", "--platform", "manylinux2014_aarch64", "--implementation", "cp", "--python-version", "3.12",
        "--only-binary=:all:", ...extra, "cryptography==46.0.5"], { stdio: "inherit" });
      for (const file of ["handler.py", "grants.py", "store.py"]) copyFileSync(path.join(functionDir, file), path.join(outputDir, file));
      return true;
    } },
    command: ["bash", "-c", "echo 'MCP bundling requires pip on the build host' >&2; exit 1"],
  } });
  const fn = new LambdaFunction(stack, "GrantFunction", { runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64,
    handler: "handler.handler", code, timeout: Duration.seconds(10), memorySize: 256,
    environment: { MCP_ORIGIN: plan.origin, MCP_GRANT_TABLE: table.tableName, MCP_KMS_KEY: key.keyArn } });
  fn.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: ["dynamodb:GetItem", "dynamodb:PutItem"], resources: [table.tableArn] }));
  key.grant(fn, "kms:GenerateDataKey", "kms:Decrypt");
  fn.addPermission("SiteComputeInvoke", { principal: new ArnPrincipal(plan.invokerRoleArn), action: "lambda:InvokeFunction" });
  return { functionArn: fn.functionArn, origin: plan.origin };
}
