import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  MAX_VISUAL_BYTES,
  VISUAL_STYLE_OWNER_ID,
  assertVisualUpload,
  byteLimitForRole,
  isVisualRole,
  mediaTypeAllowedForRole,
} from "../amplify/functions/model-attachment-upload/rules";

const SHA = "a".repeat(64);
const good = { ownerKind: "item", ownerId: VISUAL_STYLE_OWNER_ID, role: "visual_example", mediaType: "image/png", byteSize: 200_000, sha256: SHA, sortKey: SHA, filename: `${SHA}.png` };
const general = new Set(["application/json", "text/plain"]);

// The two new roles take PNG, JPEG and WebP up to 10 MB, stored under the profile's own item.
assert.doesNotThrow(() => assertVisualUpload(good));
assert.doesNotThrow(() => assertVisualUpload({ ...good, role: "visual_negative", mediaType: "image/jpeg", filename: `${SHA}.jpg` }));
assert.doesNotThrow(() => assertVisualUpload({ ...good, mediaType: "image/webp", filename: `${SHA}.webp`, byteSize: MAX_VISUAL_BYTES }));
assert.ok(isVisualRole("visual_example") && isVisualRole("visual_negative") && !isVisualRole("metadata"));

// Wrong type, too big, no hash: refused in plain words.
assert.throws(() => assertVisualUpload({ ...good, mediaType: "image/svg+xml", filename: `${SHA}.svg` }), /PNG, JPEG or WebP/);
assert.throws(() => assertVisualUpload({ ...good, mediaType: "image/gif", filename: `${SHA}.gif` }), /PNG, JPEG or WebP/);
assert.throws(() => assertVisualUpload({ ...good, byteSize: MAX_VISUAL_BYTES + 1 }), /10 MB/);
assert.throws(() => assertVisualUpload({ ...good, sha256: null }), /sha256/);

// The file is stored once, named by its hash, and only under the profile; never under a published item.
assert.throws(() => assertVisualUpload({ ...good, sortKey: "other" }), /sortKey/);
assert.throws(() => assertVisualUpload({ ...good, filename: "cover.png" }), /filename/);
assert.throws(() => assertVisualUpload({ ...good, ownerKind: "publishedItem" }), /visual style profile/);
assert.throws(() => assertVisualUpload({ ...good, ownerId: "item-some-story-v1" }), /visual style profile/);

// Images open only for the visual roles; the cap changes only for them.
assert.equal(mediaTypeAllowedForRole("visual_example", "image/png", general), true);
assert.equal(mediaTypeAllowedForRole("visual_example", "application/json", general), false);
assert.equal(mediaTypeAllowedForRole("metadata", "image/png", general), false);
assert.equal(mediaTypeAllowedForRole("metadata", "application/json", general), true);
assert.equal(byteLimitForRole("visual_example", 25 * 1024 * 1024), MAX_VISUAL_BYTES);
assert.equal(byteLimitForRole("metadata", 25 * 1024 * 1024), 25 * 1024 * 1024);

// The function applies these rules and registers the roles; items keep the private newsroom prefix.
const source = readFileSync(join(process.cwd(), "amplify/functions/model-attachment-upload/handler.ts"), "utf8");
assert.match(source, /"visual_example",\s*\n\s*"visual_negative",/);
assert.match(source, /assertVisualUpload\(/);
assert.match(source, /ownerKind === "publishedItem" \? "media\/payloads" : "newsroom\/payloads"/, "only published items are stored under the public prefix");

console.log("model attachment visual roles: ok");
