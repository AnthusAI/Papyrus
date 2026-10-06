#!/usr/bin/env node

const { execFileSync } = require("node:child_process");
const path = require("node:path");

const DEFAULT_ENDPOINT =
  process.env.PAPYRUS_GRAPHQL_ENDPOINT ||
  "https://64hviw44q5cq5nwjcigmasowlq.appsync-api.us-east-1.amazonaws.com/graphql";

const CORPUS_KEY = "AI-ML-research";
const SECTION_KEY = "science";
const STEERING_CONFIG = "corpora/papyrus-steering.yml";

const TITLE = "Immediate AI/ML academic source discovery";
const SUMMARY =
  "Find new, relevant academic research papers across LLMs, AI engineering, retrieval, representation learning, topic modeling, agent evaluation, and related methods.";
const INSTRUCTIONS = [
  "Dispatch priority: immediate cron research sweep.",
  "Research mode: source_discovery. Orient with accepted Papyrus knowledge first, then run at least one web search for fresh academic prospects.",
  "Prioritize peer-reviewed papers, preprints with clear methods, benchmark studies, and durable technical reports.",
  "Focus areas:",
  "- large language models and AI engineering practices",
  "- retrieval-augmented generation and information architectures",
  "- embeddings, encoders, and text classifiers",
  "- unsupervised, semi-supervised, and topic-modeling methods",
  "- hidden Markov models and sequence/structure learning where relevant",
  "- robotic process automation only when tied to AI/ML systems design",
  "- behavioral and operational evaluations for AI agents",
  "Prefer sources not already represented in the accepted reference set. Record blockedReason if web discovery cannot run.",
  "Return proposedReferences with ingestion_rationale tied to the Science desk mission and publication doctrine.",
].join(" ");

function main() {
  const options = parseArgs(process.argv.slice(2));
  ensureAuthoringEnv();
  const createArgs = [
    "run",
    "content",
    "--",
    "assignments",
    "create-research",
    "--title",
    TITLE,
    "--summary",
    SUMMARY,
    "--brief",
    SUMMARY,
    "--instructions",
    INSTRUCTIONS,
    "--section",
    SECTION_KEY,
    "--corpus-key",
    CORPUS_KEY,
    "--research-mode",
    "source_discovery",
    "--priority",
    "95",
    "--queue",
    "research:science:immediate",
    "--actor-label",
    "papyrus-automation-ai-ml-research-papers",
    "--apply",
    "--json",
  ];
  if (options.dryRun) createArgs.pop();
  if (options.dryRun) createArgs.pop();

  const createRaw = runNpm(createArgs);
  const createResult = JSON.parse(createRaw);
  if (!createResult.ok) {
    throw new Error(`create-research failed: ${createRaw}`);
  }
  if (options.dryRun || createResult.action !== "apply") {
    process.stdout.write(`${createRaw}\n`);
    return;
  }

  process.stdout.write(`${createRaw}\n`);
  if (!options.executeNow) {
    process.stdout.write(
      `${JSON.stringify({
        ok: true,
        phase: "assignment-dispatched",
        assignmentId: createResult.assignmentId,
        next: `npm run dispatch:ai-ml-research-papers -- --execute-now --assignment ${createResult.assignmentId}`,
      })}\n`,
    );
    return;
  }

  const assignmentId = options.assignment || createResult.assignmentId;
  const intakeRaw = runNpm([
    "run",
    "content",
    "--",
    "assignments",
    "research-intake-now",
    "--assignment",
    assignmentId,
    "--config",
    STEERING_CONFIG,
    "--corpus-key",
    CORPUS_KEY,
    "--research-mode",
    "source_discovery",
    "--max-evidence-items",
    "20",
    "--apply",
    "--json",
  ]);
  process.stdout.write(`${intakeRaw}\n`);
}

function ensureAuthoringEnv() {
  if (!process.env.PAPYRUS_GRAPHQL_ENDPOINT) {
    process.env.PAPYRUS_GRAPHQL_ENDPOINT = DEFAULT_ENDPOINT;
  }
}

function runNpm(args) {
  return execFileSync("npm", args, {
    cwd: path.resolve(__dirname, ".."),
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    env: process.env,
  });
}

function parseArgs(argv) {
  const options = { dryRun: false, executeNow: false, assignment: "" };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--dry-run") options.dryRun = true;
    if (token === "--execute-now") options.executeNow = true;
    if (token === "--assignment") options.assignment = argv[++index] ?? "";
  }
  return options;
}

main();
