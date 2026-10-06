import assert from "node:assert/strict";
import test from "node:test";
import { normalizeDevPreviewDsl, parseVideoScriptRef, videomlItemSlug } from "../lib/video-script";

test("parseVideoScriptRef reads the videoScript payload of an item", () => {
  const result = parseVideoScriptRef({
    slug: "the-balance-of-power-is-shifting--videoml",
    editorial: {
      videoScript: {
        dsl: '<vml id="the-balance-of-power-is-shifting" title="Sample" fps="30" width="1280" height="720"></vml>',
        theme: "both",
        target: { kind: "article", articleSlug: "the-balance-of-power-is-shifting" },
      },
    },
  });
  assert.equal(result?.targetKind, "article");
  assert.equal(result?.slug, "the-balance-of-power-is-shifting--videoml");
  assert.match(result?.dsl ?? "", /^<vml /);
});

test("parseVideoScriptRef accepts editorial as a JSON string and detects edition targets", () => {
  const editorial = JSON.stringify({ videoScript: { dsl: "<vml/>", target: { kind: "edition" } } });
  assert.equal(parseVideoScriptRef({ slug: "edition--videoml", editorial })?.targetKind, "edition");
});

test("parseVideoScriptRef returns null without a dsl or with unusable editorial", () => {
  assert.equal(parseVideoScriptRef({ slug: "a--videoml", editorial: {} }), null);
  assert.equal(parseVideoScriptRef({ slug: "a--videoml", editorial: { videoScript: { dsl: "   " } } }), null);
  assert.equal(parseVideoScriptRef({ slug: "a--videoml", editorial: "not json" }), null);
  assert.equal(parseVideoScriptRef({ slug: "a--videoml" }), null);
});

test("videomlItemSlug appends the stored-script suffix", () => {
  assert.equal(videomlItemSlug("my-article"), "my-article--videoml");
});

test("normalizeDevPreviewDsl applies a passed-in element alias map to opening and closing tags", () => {
  const dsl = '<layer><quote-card props="{}" /><quote-card-wide /></layer><quote-card>x</quote-card>';
  const result = normalizeDevPreviewDsl(dsl, { "quote-card": "acme-quote-card" });
  assert.equal(
    result,
    '<layer><acme-quote-card props="{}" /><quote-card-wide /></layer><acme-quote-card>x</acme-quote-card>',
  );
});

test("normalizeDevPreviewDsl without aliases leaves the script unchanged", () => {
  const dsl = '<quote-card props="{}" />';
  assert.equal(normalizeDevPreviewDsl(dsl), dsl);
  assert.equal(normalizeDevPreviewDsl(dsl, {}), dsl);
});
