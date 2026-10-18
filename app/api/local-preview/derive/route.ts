import { spawn } from "node:child_process";
import path from "node:path";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Local preview only: derives a story's Markus body through the real Python engine so directives render.
 * Set PAPYRUS_PREVIEW_PYTHON to a Python that has Papyrus and its Markus extra installed.
 */
export async function POST(request: Request) {
  if (process.env.NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW !== "1") return new NextResponse(null, { status: 404 });
  const python = process.env.PAPYRUS_PREVIEW_PYTHON?.trim();
  if (!python) return NextResponse.json({ error: "PAPYRUS_PREVIEW_PYTHON is not set." }, { status: 501 });
  const input = await request.text();
  const script = path.join(process.cwd(), "scripts", "local-preview-derive.py");
  const output = await new Promise<string>((resolve, reject) => {
    const child = spawn(python, [script], { env: process.env });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", chunk => { stdout += chunk; });
    child.stderr.on("data", chunk => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", code => code === 0 ? resolve(stdout) : reject(new Error(stderr || `derive exited with ${code}`)));
    child.stdin.end(input);
  }).catch((reason: unknown) => JSON.stringify({ error: reason instanceof Error ? reason.message : "derive failed" }));
  return new NextResponse(output, { headers: { "content-type": "application/json" } });
}
