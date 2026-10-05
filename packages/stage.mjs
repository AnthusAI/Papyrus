#!/usr/bin/env node
/**
 * Stage and pack
 * @anthusai/papyrus, with one shared version (SPIKE, PPY-82be6c).
 * Python wheel: `python -m build --wheel` at the repo root, version stamped via
 * `PAPYRUS_VERSION` (see packages/README.md).
 *
 *   node packages/stage.mjs --version 0.0.0-spike.1
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..");
const ts = createRequire(path.join(process.env.PAPYRUS_TS_RESOLVE_FROM ?? repo, "noop.js"))("typescript");
const args = process.argv.slice(2);
const version = args.includes("--version") ? args[args.indexOf("--version") + 1] : "0.0.0-spike.0";
const outRoot = path.join(repo, "dist-packages");

const pep440 = (v) => {
  const m = /^(\d+\.\d+\.\d+)(?:-[0-9A-Za-z-]+\.(\d+))?$/.exec(v);
  if (!m) throw new Error(`Cannot map ${v} to PEP 440`);
  return m[2] === undefined ? m[1] : `${m[1]}.dev${m[2]}`;
};

execFileSync("node", [path.join(here, "papyrus/scripts/stage.mjs"), "--version", version], { stdio: "inherit" });

// Python: stamp the lockstep version into a build copy (never committed back), build wheel + sdist.
const pyStage = path.join(outRoot, "stage-papyrus-newsroom");
fs.rmSync(pyStage, { recursive: true, force: true });
fs.mkdirSync(pyStage, { recursive: true });
fs.cpSync(path.join(repo, "src"), path.join(pyStage, "src"), { recursive: true, filter: (p) => !p.includes("__pycache__") });
for (const f of ["README.md", "LICENSE"]) fs.copyFileSync(path.join(repo, f), path.join(pyStage, f));
const pyproject = fs.readFileSync(path.join(repo, "pyproject.toml"), "utf8").replace(/^version = ".*"$/m, `version = "${pep440(version)}"`);
fs.writeFileSync(path.join(pyStage, "pyproject.toml"), pyproject);
const python = process.env.PAPYRUS_PYTHON || "python3";
execFileSync(python, ["-m", "build", "--outdir", outRoot, pyStage], { stdio: "inherit" });
console.log(`python: papyrus-newsroom ${pep440(version)} -> ${outRoot}`);
