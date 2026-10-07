import assert from "node:assert/strict";
import {
  isPreviewGatedPath,
  isStaticPreviewEnabled,
  previewCandidateKeys,
  previewRewritePathname,
  shouldRewriteToPreview,
} from "../lib/staging-preview-object";

assert.deepEqual(previewCandidateKeys("/"), ["preview/index.html"]);
assert.deepEqual(previewCandidateKeys("/articles/foo.html"), [
  "preview/articles/foo.html",
  "preview/articles/foo.html.html",
  "preview/articles/foo.html/index.html",
]);
assert.deepEqual(previewCandidateKeys("/articles/foo"), [
  "preview/articles/foo",
  "preview/articles/foo.html",
  "preview/articles/foo/index.html",
]);
assert.deepEqual(previewCandidateKeys("/articles/"), ["preview/articles/index.html"]);
assert.equal(previewCandidateKeys("/a/../b"), null);
assert.equal(previewCandidateKeys("//x"), null);
assert.equal(previewCandidateKeys("/a//b"), null);
assert.equal(previewCandidateKeys("/a/%2e%2e/b"), null);
assert.equal(previewCandidateKeys("/a%2F%2Fb"), null);

assert.equal(shouldRewriteToPreview("/articles/foo.html"), true);
assert.equal(shouldRewriteToPreview("/"), true);
assert.equal(shouldRewriteToPreview("/css/site-theme.css"), true);
for (const excluded of ["/newsroom", "/newsroom/articles", "/api/x", "/_next/static/a.js", "/__preview/x", "/favicon.ico", "/icon.png", "/robots.txt"]) {
  assert.equal(shouldRewriteToPreview(excluded), false, excluded);
}
assert.equal(isPreviewGatedPath("/__preview/index.html"), true);
assert.equal(isPreviewGatedPath("/newsroom"), false);
assert.equal(shouldRewriteToPreview("/", true), false);
assert.equal(shouldRewriteToPreview("/articles", true), false);
assert.equal(shouldRewriteToPreview("/articles/foo.html", true), true);
assert.equal(isPreviewGatedPath("/", true), false);
assert.equal(isPreviewGatedPath("/articles/foo.html", true), true);
assert.equal(isPreviewGatedPath("/__preview/", true), true);
assert.equal(previewRewritePathname("/articles/foo.html"), "/__preview/articles/foo.html");

assert.equal(isStaticPreviewEnabled({ SITE_ENV: "staging", PAPYRUS_STAGING_PREVIEW: "static" }), true);
assert.equal(isStaticPreviewEnabled({ SITE_ENV: "production", PAPYRUS_STAGING_PREVIEW: "static" }), false);
assert.equal(isStaticPreviewEnabled({ SITE_ENV: "staging" }), false);

console.log("staging preview keys: ok");
