/**
 * Synthesizes several configurations of a site's backend at once, each with scripts/synth-site-backend.mts in its own process.
 * One whole-backend synth takes minutes and uses one processor, so a test that needs three of them waits for the slowest
 * and not for the sum.
 *
 *   tsx scripts/synth-site-backends-side-by-side.mts '[{"out":"<dir>","environment":{"PAPYRUS_COST_TAG_WAVE":"1"},"without":["PAPYRUS_SITE_ID"]}]'
 *
 * `environment` is added to this process's environment for that synth and `without` names variables removed from it.
 * Exits non-zero, printing the output of each synth that failed, when any synth fails.
 */
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

type RequestedSynth = { out: string; environment?: Record<string, string>; without?: string[] };

const requestedSynths: RequestedSynth[] = JSON.parse(process.argv[2] ?? "[]");
if (requestedSynths.length === 0) throw new Error("usage: synth-site-backends-side-by-side.mts '[{\"out\":\"<dir>\"}]'");
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const synthesize = (requested: RequestedSynth) =>
  new Promise<{ out: string; status: number | null; output: string }>((resolve, reject) => {
    const environment: NodeJS.ProcessEnv = { ...process.env, ...requested.environment };
    for (const name of requested.without ?? []) delete environment[name];
    const synth = spawn(process.execPath, ["--import", "tsx", path.join(repo, "scripts/synth-site-backend.mts"), requested.out], { cwd: repo, env: environment });
    let output = "";
    synth.stdout.on("data", (chunk) => (output += chunk));
    synth.stderr.on("data", (chunk) => (output += chunk));
    synth.on("error", reject);
    synth.on("close", (status) => resolve({ out: requested.out, status, output }));
  });

const finished = await Promise.all(requestedSynths.map(synthesize));
const failed = finished.filter((synth) => synth.status !== 0);
for (const synth of failed) console.error(`synth to ${synth.out} failed:\n${synth.output}`);
process.exit(failed.length === 0 ? 0 : 1);
