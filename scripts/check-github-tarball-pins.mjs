#!/usr/bin/env node
/**
 * Release gate: every dependency pinned to a GitHub commit tarball must point at a commit that is
 * reachable from that repository's default branch. A commit that lives only on a feature branch can
 * vanish when the branch is rewritten or deleted, which breaks every install that resolves it.
 *   node scripts/check-github-tarball-pins.mjs [package.json]
 * A pin verifiably off the default branch is a ::warning:: annotation, or a failure when
 * PAPYRUS_PIN_CHECK_STRICT=1 (turn that on once chatticus is pinned to a merged commit). A check that
 * cannot run (no `gh`, or the token cannot read the repository) is always a warning.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const manifest = JSON.parse(fs.readFileSync(process.argv[2] ?? "package.json", "utf8"));
const TARBALL = /^https:\/\/github\.com\/([^/]+)\/([^/]+)\/archive\/([0-9a-f]{40})\.tar\.gz$/;
const pins = [];
for (const section of ["dependencies", "devDependencies", "optionalDependencies"]) {
  for (const [name, spec] of Object.entries(manifest[section] ?? {})) {
    const match = TARBALL.exec(spec);
    if (match) pins.push({ name, owner: match[1], repo: match[2], sha: match[3] });
  }
}

function gh(path) {
  return JSON.parse(execFileSync("gh", ["api", path], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }));
}

let failed = false;
for (const { name, owner, repo, sha } of pins) {
  try {
    const { default_branch: branch } = gh(`repos/${owner}/${repo}`);
    const { status } = gh(`repos/${owner}/${repo}/compare/${branch}...${sha}`);
    if (status === "identical" || status === "behind") {
      console.log(`ok: ${name} is pinned to ${sha.slice(0, 8)}, which is on ${owner}/${repo}@${branch}`);
    } else {
      const strict = process.env.PAPYRUS_PIN_CHECK_STRICT === "1";
      console.log(`${strict ? "::error::" : "::warning::"}${name} is pinned to ${sha.slice(0, 8)}, which is NOT on ${owner}/${repo}@${branch} (${status}). The commit can vanish when its branch is rewritten or deleted. Pin a merged commit or a release.`);
      failed ||= strict;
    }
  } catch (error) {
    const reason = String(error.stderr ?? error.message).split("\n")[0];
    console.log(`::warning::Cannot verify that ${name} (${owner}/${repo}@${sha.slice(0, 8)}) is on the default branch: ${reason}`);
  }
}
if (pins.length === 0) console.log("ok: no GitHub tarball pins");
process.exit(failed ? 1 : 0);
