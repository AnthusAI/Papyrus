import { Duration, Stack } from 'aws-cdk-lib';
import { ArnPrincipal } from 'aws-cdk-lib/aws-iam';
import { Architecture, Code, Function as LambdaFunction, Runtime } from 'aws-cdk-lib/aws-lambda';
import { execFileSync } from 'node:child_process';
import { pythonLambdaCode } from '../functions/shared/python-bundle';
import type { McpOAuthPlan } from '../mcp-oauth/resource';

/** Reader actions use the public site's host, not the CMS origin. */
export function readerPublication(origin: string | undefined): string {
  try {
    const url = new URL(origin ?? '');
    return url.protocol === 'https:' && url.origin === origin ? url.host : '';
  } catch { return ''; }
}

/** Only the site's compute role can hand a verified principal to this function. */
export function addMcpTools(stack: Stack, plan: McpOAuthPlan, options: { endpoint: string; tenant: string; publication: string; reader?: LambdaFunction; referenceSingleTenant?: boolean }, bundledCode?: Code) {
  const code = bundledCode ?? pythonLambdaCode({ functionDir: 'mcp-tools', modules: ['papyrus_content'], checkoutExtras: outputDir => {
    const extra = (process.env.PAPYRUS_PIP_EXTRA_ARGS ?? '').trim().split(/\s+/).filter(Boolean);
    execFileSync((process.env.PAPYRUS_PIP_PYTHON ?? 'python3').trim(), ['-m', 'pip', 'install', '--target', outputDir, '--platform', 'manylinux2014_aarch64', '--implementation', 'cp', '--python-version', '3.12', '--only-binary=:all:', ...extra, 'cli-login==0.4.1'], { stdio: 'inherit' });
  } }, [
    'bash', '-c', 'set -euo pipefail; cp amplify/functions/mcp-tools/handler.py /asset-output/handler.py; cp -R src/papyrus_content /asset-output/papyrus_content; python3 -m pip install --target /asset-output cli-login==0.4.1',
  ]);
  const fn = new LambdaFunction(stack, 'ToolsFunction', {
    runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: 'handler.handler', code,
    timeout: Duration.seconds(25), memorySize: 256,
    environment: {
      PAPYRUS_GRAPHQL_ENDPOINT: options.endpoint,
      ...(options.tenant ? { PAPYRUS_TENANT_ID: options.tenant } : {}),
      ...(options.reader && options.publication ? { PAPYRUS_READER_STEERING_FUNCTION: options.reader.functionName, PAPYRUS_PUBLICATION_ID: options.publication } : {}),
      ...(options.referenceSingleTenant && !options.tenant ? { PAPYRUS_MCP_REFERENCE_SINGLE_TENANT: 'true' } : {}),
    },
  });
  fn.addPermission('SiteComputeInvoke', { principal: new ArnPrincipal(plan.invokerRoleArn), action: 'lambda:InvokeFunction' });
  if (options.reader && options.publication) options.reader.grantInvoke(fn);
  return { functionArn: fn.functionArn };
}
