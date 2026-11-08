import { Duration, Stack } from 'aws-cdk-lib';
import { ArnPrincipal } from 'aws-cdk-lib/aws-iam';
import { Architecture, Code, Function as LambdaFunction, Runtime } from 'aws-cdk-lib/aws-lambda';
import { execFileSync } from 'node:child_process';
import { packageRoot, pythonLambdaCode } from '../functions/shared/python-bundle';
import type { McpOAuthPlan } from '../mcp-oauth/resource';

/** Reader actions use the public site's host, not the CMS origin. */
export function readerPublication(origin: string | undefined): string {
  try {
    const url = new URL(origin ?? '');
    return url.protocol === 'https:' && url.origin === origin ? url.host : '';
  } catch { return ''; }
}

export function mcpBrowserOptions(env: Record<string, string | undefined>) {
  const appsEnabled = env.PAPYRUS_MCP_APPS === 'true';
  const origins = (env.PAPYRUS_MCP_ALLOWED_ORIGINS ?? '').split(',').map(value => value.trim()).filter(Boolean);
  for (const origin of origins) {
    let url: URL;
    try { url = new URL(origin); } catch { throw new Error('MCP browser origins must be exact HTTPS origins'); }
    if (url.protocol !== 'https:' || url.origin !== origin || url.username || url.password || origin.includes('*')) throw new Error('MCP browser origins must be exact HTTPS origins');
  }
  return { appsEnabled, allowedOrigins: [...new Set(origins)] };
}

/** Only the site's compute role can hand a verified principal to this function. */
export function addMcpTools(stack: Stack, plan: McpOAuthPlan, options: { endpoint: string; tenant: string; publication: string; reader?: LambdaFunction; referenceSingleTenant?: boolean; storyPublishRequests?: boolean; storyDrafts?: boolean }, bundledCode?: Code) {
  const code = bundledCode ?? pythonLambdaCode({ functionDir: 'mcp-tools', modules: ['papyrus_content'], checkoutExtras: outputDir => {
    const extra = (process.env.PAPYRUS_PIP_EXTRA_ARGS ?? '').trim().split(/\s+/).filter(Boolean);
    // Install the local project's declared runtime dependencies, preserving checkout source.
    execFileSync((process.env.PAPYRUS_PIP_PYTHON ?? 'python3').trim(), ['-m', 'pip', 'install', '--target', outputDir, '--platform', 'manylinux2014_aarch64', '--implementation', 'cp', '--python-version', '3.12', '--only-binary=:all:', ...extra, packageRoot], { stdio: 'inherit' });
  } }, [
    'bash', '-c', 'set -euo pipefail; python3 -m pip install --target /asset-output /asset-input; cp amplify/functions/mcp-tools/handler.py /asset-output/handler.py; cp -R src/papyrus_content/. /asset-output/papyrus_content/',
  ]);
  const fn = new LambdaFunction(stack, 'ToolsFunction', {
    runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: 'handler.handler', code,
    timeout: Duration.seconds(25), memorySize: 256,
    environment: {
      PAPYRUS_GRAPHQL_ENDPOINT: options.endpoint,
      // The same site backend provisions the conditional draft mutation and Item transaction grant.
      PAPYRUS_MCP_STORY_DRAFT_ENABLED: 'true',
      ...(options.tenant ? { PAPYRUS_TENANT_ID: options.tenant } : {}),
      ...(options.reader && options.publication ? { PAPYRUS_READER_STEERING_FUNCTION: options.reader.functionName, PAPYRUS_PUBLICATION_ID: options.publication } : {}),
      ...(options.referenceSingleTenant && !options.tenant ? { PAPYRUS_MCP_REFERENCE_SINGLE_TENANT: 'true' } : {}),
      ...(options.storyPublishRequests && !options.tenant ? { PAPYRUS_MCP_STORY_PUBLISH_REQUEST_ENABLED: 'true' } : {}),
      ...(options.storyDrafts ? { PAPYRUS_MCP_STORY_DRAFT_ENABLED: 'true' } : {}),
    },
  });
  fn.addPermission('SiteComputeInvoke', { principal: new ArnPrincipal(plan.invokerRoleArn), action: 'lambda:InvokeFunction' });
  if (options.reader && options.publication) options.reader.grantInvoke(fn);
  return { functionArn: fn.functionArn };
}
