/** Stateless Streamable HTTP transport. Authentication and authorization are injected. */
export type McpTool = { name: string; inputSchema: Record<string, unknown>; [key: string]: unknown };
export type McpToolResult = { content: Array<Record<string, unknown>>; structuredContent?: Record<string, unknown>; isError?: boolean; [key: string]: unknown };
export type McpDependencies<P> = {
  enabled: boolean;
  verifyBearer: (token: string, request: Request) => Promise<P | null>;
  listTools: (principal: P) => Promise<McpTool[]>;
  callTool: (principal: P, name: string, args: Record<string, unknown>, availableTools: string[]) => Promise<McpToolResult>;
  listResources?: (principal: P) => Promise<Array<Record<string, unknown>>>;
  readResource?: (principal: P, uri: string) => Promise<Record<string, unknown>>;
  allowedOrigins?: string[];
  resourceMetadataUrl?: string;
};

const versions = ["2025-11-25", "2025-06-18", "2025-03-26"];
const maxBodyBytes = 1024 * 1024;
const accepts = (header: string, type: string) => header.split(",").some(part => {
  const [media, ...parameters] = part.trim().toLowerCase().split(";");
  return media.trim() === type && !parameters.some(parameter => /^\s*q\s*=\s*0(?:\.0*)?\s*$/.test(parameter));
});
const headers = { "Cache-Control": "no-store" };
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const json = (value: unknown, status = 200, additional: Record<string, string> = {}) => Response.json(value, { status, headers: { ...headers, ...additional } });
const error = (id: unknown, code: number, message: string, status = 200) => json({ jsonrpc: "2.0", id: id ?? null, error: { code, message } }, status);

export function createMcpHandler<P>(deps: McpDependencies<P>) {
  const handle = async (request: Request): Promise<Response> => {
    if (!deps.enabled || !deps.resourceMetadataUrl) return new Response(null, { status: 404, headers });
    const origin = request.headers.get("origin");
    if (origin && !deps.allowedOrigins?.includes(origin)) return new Response(null, { status: 403, headers });
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
    const match = /^Bearer\s+(\S+)$/i.exec(request.headers.get("authorization") ?? "");
    let principal: P | null = null;
    try { if (match) principal = await deps.verifyBearer(match[1], request); } catch { return new Response(null, { status: 503, headers }); }
    if (principal === null) {
      const metadata = deps.resourceMetadataUrl;
      return new Response(null, { status: 401, headers: { ...headers, "WWW-Authenticate": `Bearer resource_metadata="${metadata}"` } });
    }
    const version = request.headers.get("mcp-protocol-version");
    if (version && !versions.includes(version)) return error(null, -32600, "Unsupported protocol version", 400);
    if (request.method !== "POST") return new Response(null, { status: 405, headers: { ...headers, Allow: "POST" } });
    const accept = request.headers.get("accept") ?? "";
    if (!accepts(accept, "application/json") || !accepts(accept, "text/event-stream")) return error(null, -32600, "Accept must include application/json and text/event-stream", 406);
    if (!/^application\/json(?:\s*;|\s*$)/i.test(request.headers.get("content-type") ?? "")) return error(null, -32600, "Expected application/json", 415);
    let message: unknown;
    try {
      const reader = request.body?.getReader();
      const chunks: Uint8Array[] = [];
      let length = 0;
      if (reader) {
        while (true) {
          const next = await reader.read();
          if (next.done) break;
          length += next.value.byteLength;
          if (length > maxBodyBytes) { await reader.cancel(); return error(null, -32600, "Request too large", 413); }
          chunks.push(next.value);
        }
      }
      const bytes = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      message = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    } catch { return error(null, -32700, "Parse error", 400); }
    if (object(message) && message.jsonrpc === "2.0" && (typeof message.id === "string" || typeof message.id === "number") && !("method" in message) && (("result" in message) !== ("error" in message))) return new Response(null, { status: 202, headers });
    if (!object(message) || message.jsonrpc !== "2.0" || typeof message.method !== "string" || (message.params !== undefined && !object(message.params)) || ("id" in message && typeof message.id !== "string" && typeof message.id !== "number")) return error(null, -32600, "Invalid Request", 400);
    if (!("id" in message)) return new Response(null, { status: 202, headers });
    const id = message.id;
    const params = object(message.params) ? message.params : {};
    let result: unknown;
    try {
      switch (message.method) {
        case "initialize": {
          if (typeof params.protocolVersion !== "string" || !object(params.capabilities) || !object(params.clientInfo)) return error(id, -32602, "Invalid params");
          result = { protocolVersion: versions.includes(params.protocolVersion) ? params.protocolVersion : versions[0], capabilities: { tools: {}, ...(deps.listResources && deps.readResource ? { resources: {} } : {}) }, serverInfo: { name: "papyrus", version: "1.0.0" } };
          break;
        }
        case "ping": result = {}; break;
        case "tools/list": result = { tools: await deps.listTools(principal) }; break;
        case "tools/call":
          if (typeof params.name !== "string" || (params.arguments !== undefined && !object(params.arguments))) return error(id, -32602, "Invalid params");
          // Discovery is not authorization: reject names unavailable to this principal on every call.
          {
            const available = (await deps.listTools(principal)).map(tool => tool.name);
            if (!available.includes(params.name)) return error(id, -32602, "Unknown or unavailable tool");
            result = await deps.callTool(principal, params.name, object(params.arguments) ? params.arguments : {}, available);
          }
          break;
        case "resources/list":
          if (!deps.listResources || !deps.readResource) return error(id, -32601, "Method not found");
          result = { resources: await deps.listResources(principal) }; break;
        case "resources/read":
          if (!deps.listResources || !deps.readResource) return error(id, -32601, "Method not found");
          if (typeof params.uri !== "string") return error(id, -32602, "Invalid params");
          result = await deps.readResource(principal, params.uri); break;
        default: return error(id, -32601, "Method not found");
      }
      return json({ jsonrpc: "2.0", id, result });
    } catch { return error(id, -32603, "Internal error"); }
  };
  return async (request: Request): Promise<Response> => {
    const response = await handle(request);
    const origin = request.headers.get("origin");
    if (!origin || !deps.enabled || !deps.resourceMetadataUrl || !deps.allowedOrigins?.includes(origin)) return response;
    const cors = new Headers(response.headers);
    cors.set("Access-Control-Allow-Origin", origin);
    cors.set("Vary", "Origin");
    cors.set("Access-Control-Allow-Methods", "POST, OPTIONS");
    cors.set("Access-Control-Allow-Headers", "Authorization, Content-Type, MCP-Protocol-Version");
    cors.set("Access-Control-Expose-Headers", "WWW-Authenticate, MCP-Protocol-Version");
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers: cors });
  };
}
