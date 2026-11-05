import { createMcpHandler } from "@/lib/mcp/transport";

// No endpoint is exposed until a verified identity and domain adapter are wired.
const handler = createMcpHandler({
  enabled: false,
  verifyBearer: async () => null,
  listTools: async () => [],
  callTool: async () => ({ content: [] }),
});

export const dynamic = "force-dynamic";
export const GET = handler;
export const POST = handler;
export const DELETE = handler;
