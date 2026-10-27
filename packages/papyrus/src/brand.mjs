import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

/**
 * `papyrus-app brand diff <id>`: compare a site's own `publication/` brand pack with the reference pack in a
 * Papyrus checkout (`publications/<id with "-" as "_">/`).
 *
 * Brand packs are NOT in the npm package (staging refuses to ship publication code), so a site owns a copy and
 * nothing upgrades it. This command is the drift check: run it after a Papyrus upgrade to see what the reference
 * pack gained (a logo component, CSS, a font) that the site's copy lacks. It only reads; it never writes.
 */
const SKIPPED = new Set(["README.md", "index.ts"]);
const PKG = "@anthusai/papyrus";

export function referenceDirFor(id, checkout) {
  return path.join(checkout, "publications", id.replace(/-/g, "_"));
}

function listFiles(dir, base = dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? listFiles(full, base) : [path.relative(base, full)];
  });
}

/** The reference pack imports Papyrus by relative path; a site imports it from the package. */
export function normalizeImports(text) {
  return text.replace(/(["'])(?:\.\.\/){2}(lib\/[^"']+)\1/g, `$1${PKG}/$2$1`);
}

function sameFile(a, b) {
  const left = fs.readFileSync(a);
  const right = fs.readFileSync(b);
  if (left.equals(right)) return true;
  if (/\.(tsx?|css|mjs|json)$/.test(a)) return normalizeImports(left.toString("utf8")) === normalizeImports(right.toString("utf8"));
  return false;
}

export function brandDiff({ root = process.cwd(), id, checkout = path.resolve(root, "..", "Papyrus"), log = console.log } = {}) {
  if (!id) throw new Error("Usage: papyrus-app brand diff <brand-id> [--papyrus <checkout>]");
  const reference = referenceDirFor(id, checkout);
  if (!fs.existsSync(reference)) throw new Error(`No reference pack for "${id}" at ${reference}. Pass --papyrus <path to a Papyrus checkout>.`);
  const site = path.join(root, "publication");
  const wanted = listFiles(reference).filter((f) => !SKIPPED.has(f));
  const have = listFiles(site).filter((f) => !SKIPPED.has(f));
  const missing = wanted.filter((f) => !have.includes(f));
  const extra = have.filter((f) => !wanted.includes(f));
  const changed = wanted.filter((f) => have.includes(f) && !sameFile(path.join(reference, f), path.join(site, f)));
  for (const f of missing) log(`  missing in site: ${f}`);
  for (const f of extra) log(`  site-only: ${f}`);
  for (const f of changed) {
    log(`  differs: ${f}`);
    if (/\.(tsx?|css)$/.test(f)) {
      const out = spawnSync("diff", ["-u", path.join(reference, f), path.join(site, f)], { encoding: "utf8" }).stdout ?? "";
      log(out.split("\n").slice(0, 40).join("\n"));
    }
  }
  const drifted = missing.length + changed.length > 0;
  log(drifted
    ? `papyrus-app brand diff: publication/ has drifted from ${reference} (${missing.length} missing, ${changed.length} differing, ${extra.length} site-only). Site-specific edits are expected to differ; anything the reference gained should be copied over.`
    : `papyrus-app brand diff: publication/ matches ${reference}${extra.length ? ` (${extra.length} site-only file(s))` : ""}`);
  return { missing, extra, changed, drifted };
}
