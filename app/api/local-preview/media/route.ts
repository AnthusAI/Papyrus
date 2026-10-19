import { spawn } from "node:child_process";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const CONTENT_TYPES: Record<string, string> = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", gif: "image/gif", webp: "image/webp", svg: "image/svg+xml", avif: "image/avif" };

/**
 * Local preview only: streams one story image from the publication's storage bucket so the previews show real figures.
 * Set PAPYRUS_PREVIEW_MEDIA_BUCKET to the bucket; the server's AWS credentials do the reading.
 */
export async function GET(request: Request) {
  if (process.env.NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW !== "1") return new NextResponse(null, { status: 404 });
  const bucket = process.env.PAPYRUS_PREVIEW_MEDIA_BUCKET?.trim();
  const key = new URL(request.url).searchParams.get("key") ?? "";
  if (!bucket) return NextResponse.json({ error: "PAPYRUS_PREVIEW_MEDIA_BUCKET is not set." }, { status: 501 });
  if (!/^media\/[A-Za-z0-9_\-./]+$/.test(key) || key.includes("..")) return new NextResponse(null, { status: 400 });
  const extension = key.split(".").pop()?.toLowerCase() ?? "";
  const child = spawn("aws", ["s3", "cp", `s3://${bucket}/${key}`, "-"], { env: process.env });
  const chunks: Buffer[] = [];
  child.stdout.on("data", chunk => chunks.push(chunk));
  const exitCode = await new Promise<number>(resolve => { child.on("close", code => resolve(code ?? 1)); child.on("error", () => resolve(1)); });
  if (exitCode !== 0) return new NextResponse(null, { status: 404 });
  return new NextResponse(Buffer.concat(chunks), { headers: { "content-type": CONTENT_TYPES[extension] ?? "application/octet-stream", "cache-control": "private, max-age=300" } });
}
