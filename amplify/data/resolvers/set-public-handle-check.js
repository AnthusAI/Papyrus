// setPublicHandle, step 2 of 3: a handle is 3 to 24 lowercase letters, digits or hyphens, starts and ends with a letter or digit,
// has no at sign, is not reserved, and is used by nobody else. The rules are the same as lib/public-handle.ts (the shared vectors in
// scripts/fixtures/public-handle-vectors.json run against both). Clearing (null or empty) skips the checks.
import { util } from "@aws-appsync/utils";
import * as ddb from "@aws-appsync/utils/dynamodb";

const RESERVED = ["admin", "editor", "ai", "papyrus", "anonymous"];

const ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-";
const RULE = "3 to 24 letters, digits and hyphens";

function refusal(handle) {
  if (handle.indexOf("@") >= 0) return RULE;
  for (const character of handle.split("")) {
    if (ALPHABET.indexOf(character) < 0) return RULE;
  }
  if (handle.length < 3 || handle.length > 24) return RULE;
  if (handle.startsWith("-") || handle.endsWith("-")) return RULE;
  if (RESERVED.indexOf(handle) >= 0) return "That handle is reserved";
  return null;
}

export function request(ctx) {
  const raw = typeof ctx.args.handle === "string" ? ctx.args.handle.trim().toLowerCase() : "";
  if (!raw) {
    ctx.stash.handle = null;
    return ddb.get({ key: { id: ctx.stash.profileId } });
  }
  const problem = refusal(raw);
  if (problem) util.error(problem, "BadRequest");
  ctx.stash.handle = raw;
  return ddb.query({ index: "userProfilesByPublicHandle", query: { publicHandle: { eq: raw } } });
}

export function response(ctx) {
  if (ctx.error) util.error(ctx.error.message, ctx.error.type);
  if (ctx.stash.handle === null) return ctx.result;
  for (const item of ctx.result.items || []) {
    if (item.id !== ctx.stash.profileId) util.error("That handle is taken", "Conflict");
  }
  return ctx.result;
}
