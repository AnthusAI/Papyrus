import { createSiteMcpHandler } from '@/lib/mcp/server';

export const dynamic = 'force-dynamic';
const handler = createSiteMcpHandler();
export const GET = handler;
export const POST = handler;
export const DELETE = handler;
export const OPTIONS = handler;
