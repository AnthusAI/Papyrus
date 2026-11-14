/** Story detail headline image: which front matter key names it, how it resolves for site media and remote pictures, and every state the view shows. Synthetic data. */
import test from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import * as React from "react";
(globalThis as { React?: unknown }).React = React;
import { StoryHeadlineImage } from "../components/story-headline-image";
import { headlineImageState, readHeadlineImage, type MediaIndex } from "../lib/story-headline-image";

const loaded = (assets: MediaIndex["assets"] = []): MediaIndex => ({ loaded: true, failed: false, assets });
const asset = (srcPath: string, storagePath: string | null) => ({ id: "m1", sortKey: "001", storagePath, alt: "", srcPath });
const html = (state: ReturnType<typeof headlineImageState>) => renderToStaticMarkup(React.createElement(StoryHeadlineImage, { state }));

test("the first of image, cover, ogImage, thumbnail with text is the headline image", () => {
  assert.equal(readHeadlineImage("title: T\nthumbnail: /a/t.png\nogImage: /a/o.png\n")?.key, "ogImage");
  assert.equal(readHeadlineImage("image: ''\ncover: /a/c.png\n")?.key, "cover");
  assert.equal(readHeadlineImage("title: T\n"), null);
  assert.equal(readHeadlineImage("image: [broken"), null);
});

test("a site-media value loses its leading slash to match the media rows", () => {
  const ref = readHeadlineImage("image: /slug/pic.jpg\n");
  assert.equal(ref?.mediaPath, "slug/pic.jpg");
  assert.equal(readHeadlineImage("image: media/slug/pic.jpg\n")?.mediaPath, "slug/pic.jpg");
  assert.equal(readHeadlineImage("image: https://example.test/p.jpg\n")?.remote, true);
});

test("alt text comes from the body figure, then the cover record, then the title", () => {
  const body = '::image{src="slug/pic.jpg" alt="Turbines at dawn"}\n';
  assert.equal(readHeadlineImage("image: /slug/pic.jpg\ntitle: T\n", body)?.alt, "Turbines at dawn");
  assert.equal(readHeadlineImage("image: /slug/pic.jpg\ntitle: T\ncoverImage:\n  title: Cover title\n", "")?.alt, "Cover title");
  assert.equal(readHeadlineImage("image: /slug/pic.jpg\ntitle: Story title\n", "")?.alt, "Story title");
});

test("no image says so in words", () => {
  assert.match(html(headlineImageState(null, loaded(), {})), /data-story-headline-image="none"[^>]*>.*No headline image/s);
});

test("a resolved picture is shown with its alt text", () => {
  const ref = readHeadlineImage("image: /slug/pic.jpg\ntitle: Wind\n");
  const out = html(headlineImageState(ref, loaded([asset("slug/pic.jpg", "media/slug/pic.jpg")]), { "slug/pic.jpg": "https://signed.test/x" }));
  assert.match(out, /data-story-headline-image="ready"/);
  assert.match(out, /<img alt="Wind"[^>]*src="https:\/\/signed.test\/x"/);
});

test("media not yet listed is loading; an asset without a file is processing", () => {
  const ref = readHeadlineImage("image: /slug/pic.jpg\n");
  assert.equal(headlineImageState(ref, { loaded: false, failed: false, assets: [] }, {}).status, "loading");
  const processing = headlineImageState(ref, loaded([asset("slug/pic.jpg", null)]), {});
  assert.equal(processing.status, "processing");
  assert.match(html(processing), /still processing/);
});

test("a named file with no media row, an unreadable object and a failed list each give a clear sentence", () => {
  const ref = readHeadlineImage("image: /slug/pic.jpg\n");
  const noRow = headlineImageState(ref, loaded(), {});
  assert.equal(noRow.status, "missing");
  assert.match(html(noRow), /no media file with that name/);
  const unreadable = headlineImageState(ref, loaded([asset("slug/pic.jpg", "media/slug/pic.jpg")]), {});
  assert.match(html(unreadable), /could not be read from storage/);
  const failed = headlineImageState(ref, { loaded: true, failed: true, assets: [] }, {});
  assert.match(html(failed), /media list could not be read/);
});

test("a draft version's own front matter decides the picture", () => {
  const published = readHeadlineImage("image: /slug/old.jpg\n");
  const draft = readHeadlineImage("image: /slug/new.jpg\n");
  const urls = { "slug/old.jpg": "https://signed.test/old", "slug/new.jpg": "https://signed.test/new" };
  assert.equal((headlineImageState(published, loaded(), urls) as { url: string }).url, "https://signed.test/old");
  assert.equal((headlineImageState(draft, loaded(), urls) as { url: string }).url, "https://signed.test/new");
});
