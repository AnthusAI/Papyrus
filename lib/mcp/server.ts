import { createMcpHandler, type McpTool, type McpToolResult } from './transport';
import { invokeMcpOAuth, mcpOAuthConfig, type McpPrincipal } from './oauth-runtime';
import { listMcpAppResources, readMcpAppResource, withMcpAppMetadata, withMcpAppResult } from './cards';
import { readAmplifyOutputsFile } from '../amplify-outputs-path';

type Config = { functionArn: string };
type DomainRequest = { operation: 'list' | 'call'; principal: McpPrincipal; name?: string; arguments?: Record<string, unknown> };
type Options = { oauth?: ReturnType<typeof mcpOAuthConfig>; domain?: Config | null; verify?: typeof invokeMcpOAuth; invoke?: (arn: string, request: DomainRequest) => Promise<unknown> };

function domainConfig(): Config | null {
  const outputs = readAmplifyOutputsFile() as { custom?: { mcpTools?: Config } } | null;
  const config = outputs?.custom?.mcpTools;
  return config && typeof config.functionArn === "string" && /^arn:aws[a-z-]*:lambda:[a-z0-9-]+:\d{12}:function:.+$/.test(config.functionArn) ? config : null;
}
async function invokeDomain(arn: string, request: DomainRequest): Promise<unknown> {
  const { LambdaClient, InvokeCommand } = await import('@aws-sdk/client-lambda');
  const response = await new LambdaClient({ region: arn.split(':')[3] }).send(new InvokeCommand({ FunctionName: arn, InvocationType: 'RequestResponse', Payload: Buffer.from(JSON.stringify(request)) }));
  if (response.FunctionError || !response.Payload) throw new Error('MCP tools service failed');
  return JSON.parse(Buffer.from(response.Payload).toString('utf8'));
}
const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

/** Build from trusted deployment outputs, never the incoming Host header. */
export function createSiteMcpHandler(options: Options = {}) {
  const oauth = options.oauth === undefined ? mcpOAuthConfig() : options.oauth;
  const domain = options.domain === undefined ? domainConfig() : options.domain;
  const invoke = options.invoke ?? invokeDomain;
  const list = async (principal: McpPrincipal): Promise<McpTool[]> => {
    if (!domain) throw new Error('MCP tools are not configured');
    const result = await invoke(domain.functionArn, { operation: 'list', principal });
    if (!isObject(result) || !Array.isArray(result.tools) || !result.tools.every((tool: unknown) => isObject(tool) && typeof tool.name === 'string' && isObject(tool.inputSchema))) throw new Error('Invalid MCP tools response');
    return (result.tools as McpTool[]).map(withMcpAppMetadata);
  };
  return createMcpHandler<McpPrincipal>({
    enabled: !!oauth && !!domain,
    resourceMetadataUrl: oauth ? `${oauth.origin}/api/mcp/oauth/resource` : undefined,
    verifyBearer: async token => {
      if (!oauth) return null;
      const result = await (options.verify ?? invokeMcpOAuth)({ operation: 'verify', token, resource: `${oauth.origin}/api/mcp` });
      if (!('principal' in result)) throw new Error('Invalid verification response');
      const principal = result.principal;
      if (principal === null) return null;
      if (principal.kind === 'reader') return { kind: 'reader', siteSubject: principal.siteSubject };
      const raw = principal as unknown as Record<string, unknown>;
      if (typeof raw.idToken !== 'string' || !raw.idToken) throw new Error('Invalid staff identity');
      return { kind: 'staff', subject: principal.subject, idToken: raw.idToken } as unknown as McpPrincipal;
    },
    listTools: list,
    callTool: async (principal, name, args) => {
      if (!domain) throw new Error('MCP tools are not configured');
      const result = await invoke(domain.functionArn, { operation: 'call', principal, name, arguments: args });
      if (!isObject(result) || !Array.isArray(result.content)) throw new Error('Invalid MCP tool result');
      return withMcpAppResult(result as McpToolResult, (await list(principal)).map(tool => tool.name));
    },
    listResources: async () => listMcpAppResources(),
    readResource: async (_principal, uri) => readMcpAppResource(uri),
  });
}
