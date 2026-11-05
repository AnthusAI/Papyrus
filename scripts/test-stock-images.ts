/** Stock image cover picker (PPY-5c9e9a): licences, Commons parsing and paging, search target, picture checks, the editor-only route, the cover text. Synthetic data, no network. */
import assert from "node:assert/strict";
import test from "node:test";
import { SimpleJwksCache } from "aws-jwt-verify/jwk";
import { SignJWT, exportJWK, generateKeyPair } from "jose";
import { NextRequest } from "next/server";
import { renderToStaticMarkup } from "react-dom/server";
import * as React from "react";
import { createElement } from "react";
(globalThis as { React?: unknown }).React = React; // the component is compiled for Next's automatic JSX; this runner uses the classic one
import { CoverImagePickerView, type PickerViewProps } from "../components/cover-image-picker";
import { newsroomChatIdentityResolver } from "../lib/newsroom-chat-identity";
import { candidateFromPage, cleanTarget, createCommonsSource, plainText, userAgent, type CommonsPage } from "../lib/stock-images/commons";
import { bodyWithCover, coverDirective, coverRecord, creditLine, frontMatterWithCover, readCoverRecord, replaceableCoverSources } from "../lib/stock-images/cover";
import { createDemoStockImageClient, demoCandidate } from "../lib/stock-images/demo-client";
import { allowedLicence } from "../lib/stock-images/licences";
import { PictureRefused, readPicture } from "../lib/stock-images/picture";
import { handleStockImageRequest } from "../lib/stock-images/route";
import { deriveSearchTarget } from "../lib/stock-images/search-target";
import { SourceBusy } from "../lib/stock-images/types";

// ---- synthetic Commons answers -------------------------------------------------------------------------------------------------------

type Overrides = { meta?: Record<string, string | null>; info?: Record<string, unknown>; title?: string };
function page(name: string, index: number, overrides: Overrides = {}): CommonsPage {
  const meta: Record<string, string | null> = {
    LicenseShortName: "CC BY 4.0", LicenseUrl: "https://creativecommons.org/licenses/by/4.0", Artist: '<a href="//commons.wikimedia.org/wiki/User:Example">Ana &amp; Bo Example</a>',
    Copyrighted: "True", ObjectName: `Object ${name}`, ImageDescription: `A <b>synthetic</b> picture called ${name}.`, ...overrides.meta,
  };
  const extmetadata: Record<string, { value: string }> = {};
  for (const [key, value] of Object.entries(meta)) if (value !== null) extmetadata[key] = { value };
  return {
    title: overrides.title ?? `File:${name}.jpg`, index,
    imageinfo: [{
      width: 3000, height: 2000, thumbwidth: 1280, thumbheight: 853, mime: "image/jpeg",
      thumburl: `https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/${name}.jpg/1280px-${name}.jpg`, url: `https://upload.wikimedia.org/wikipedia/commons/a/ab/${name}.jpg`,
      descriptionurl: `https://commons.wikimedia.org/wiki/File:${name}.jpg`, extmetadata, ...overrides.info,
    }],
  };
}
const answer = (pages: CommonsPage[], next?: number) => new Response(JSON.stringify({ query: { pages }, ...(next === undefined ? {} : { continue: { gsroffset: next } }) }), { status: 200, headers: { "content-type": "application/json" } });

// ---- licences ------------------------------------------------------------------------------------------------------------------------

test("only public domain, CC0 and CC BY are offered; share-alike, non-commercial and unknown are not", () => {
  const url = "https://creativecommons.org/licenses/by/4.0";
  assert.equal(allowedLicence({ shortName: "CC BY 4.0", url, copyrighted: "True" })?.kind, "cc-by");
  assert.equal(allowedLicence({ shortName: "CC BY 2.0", url, copyrighted: null })?.kind, "cc-by");
  assert.equal(allowedLicence({ shortName: "CC BY 3.0 DE", url, copyrighted: null })?.kind, "cc-by");
  assert.equal(allowedLicence({ shortName: "CC0", url: null, copyrighted: "False" })?.kind, "cc0");
  assert.equal(allowedLicence({ shortName: "Public domain", url: null, copyrighted: "False" })?.kind, "public-domain");
  assert.equal(allowedLicence({ shortName: "Public domain", url: null, copyrighted: "True" }), null, "a public domain tag on a file marked copyrighted is inconsistent");
  assert.equal(allowedLicence({ shortName: "CC BY 4.0", url: null, copyrighted: null }), null, "a CC licence without its address cannot be credited");
  assert.equal(allowedLicence({ shortName: "CC BY 4.0", url: "http://creativecommons.org/licenses/by/4.0", copyrighted: null }), null);
  for (const name of ["CC BY-SA 4.0", "CC BY-SA 2.0", "CC BY-NC 4.0", "CC BY-ND 2.0", "CC BY-NC-SA 3.0", "GFDL", "GPL", "Attribution", "Fair use", "", "No restrictions"]) {
    assert.equal(allowedLicence({ shortName: name, url, copyrighted: null }), null, name);
  }
  assert.equal(allowedLicence({ shortName: null, url, copyrighted: null }), null);
});

// ---- one API page -> candidate --------------------------------------------------------------------------------------------------------

test("a good page becomes a credited candidate with the licence, creator and file page from the structured data", () => {
  const result = candidateFromPage(page("Harbour", 1));
  assert.ok("candidate" in result);
  const { candidate } = result;
  assert.equal(candidate.id, "File:Harbour.jpg");
  assert.equal(candidate.creator, "Ana & Bo Example");
  assert.equal(candidate.licence.name, "CC BY 4.0");
  assert.equal(candidate.licence.url, "https://creativecommons.org/licenses/by/4.0");
  assert.equal(candidate.sourceUrl, "https://commons.wikimedia.org/wiki/File:Harbour.jpg");
  assert.equal(candidate.description, "A synthetic picture called Harbour.");
  assert.equal(candidate.width, 1280);
  assert.ok(candidate.imageUrl.startsWith("https://upload.wikimedia.org/"));
  assert.equal(creditLine(candidate), "Image: Ana & Bo Example, CC BY 4.0, via Wikimedia Commons");
});

test("a page without usable licence data, creator, type, size or address is dropped, with the reason", () => {
  const dropped = (overrides: Overrides) => {
    const result = candidateFromPage(page("X", 1, overrides));
    assert.ok("dropped" in result, JSON.stringify(overrides));
    return result.dropped;
  };
  assert.match(dropped({ meta: { LicenseShortName: "CC BY-SA 4.0" } }), /not offered/);
  assert.match(dropped({ meta: { LicenseShortName: "CC BY-NC 4.0" } }), /not offered/);
  assert.match(dropped({ meta: { LicenseShortName: null } }), /not offered/);
  assert.match(dropped({ meta: { LicenseUrl: null } }), /not offered/);
  assert.match(dropped({ meta: { Artist: null } }), /creator/);
  assert.match(dropped({ meta: { Artist: "<span>Unknown author</span>" } }), /creator/);
  assert.match(dropped({ meta: { NonFree: "true" } }), /non-free/);
  assert.match(dropped({ meta: { Restrictions: "personality" } }), /restrictions/);
  assert.match(dropped({ info: { mime: "image/gif" } }), /not offered/);
  assert.match(dropped({ info: { mime: "image/svg+xml" } }), /not offered/);
  assert.match(dropped({ info: { width: 500, height: 300, thumbwidth: 1280, thumbheight: 768 } }), /500 px wide/);
  assert.match(dropped({ info: { thumburl: "https://evil.example/x.jpg" } }), /picture address/);
  assert.match(dropped({ info: { thumburl: "http://upload.wikimedia.org/x.jpg" } }), /picture address/);
  assert.match(dropped({ info: { descriptionurl: "https://evil.example/File:X.jpg" } }), /file page/);
  assert.match(dropped({ info: { extmetadata: undefined } }), /licence metadata/);
  assert.match(dropped({ info: { extmetadata: {} } }), /not offered/);
  assert.ok("dropped" in candidateFromPage({ title: "File:Y.jpg" }));
});

test("a public domain file with no licence address is offered; a small original uses its own address", () => {
  const result = candidateFromPage(page("Old", 1, { meta: { LicenseShortName: "Public domain", LicenseUrl: null, Copyrighted: "False" }, info: { width: 1000, height: 700, thumbwidth: 1280, thumbheight: 896 } }));
  assert.ok("candidate" in result);
  assert.equal(result.candidate.licence.url, null);
  assert.equal(result.candidate.width, 1000);
  assert.ok(result.candidate.imageUrl.endsWith("/a/ab/Old.jpg"), "unscaled original");
});

test("plain text strips tags, decodes entities and never returns markup", () => {
  assert.equal(plainText('<a href="x">A &amp; B</a> &#169; &#x41; &lt;b&gt;'), "A & B © A <b>");
  assert.equal(cleanTarget('solar "panels" {x} | insource:evil'), "solar panels x insource evil");
  assert.ok(cleanTarget("x".repeat(500)).length <= 120);
  assert.match(userAgent(), /^PapyrusNewsroomImagePicker\/1\.0 \(https:\/\/github\.com\/AnthusAI\/Papyrus\) /);
});

// ---- the source: paging, exclusion, etiquette -----------------------------------------------------------------------------------------

function fakeSource(responses: Response[]) {
  const calls: { url: URL; headers: Record<string, string> }[] = [];
  let running = 0;
  let overlapped = false;
  const sleeps: number[] = [];
  const source = createCommonsSource({
    contact: "https://example.test/contact",
    sleep: async (ms) => { sleeps.push(ms); },
    now: () => 1_000_000 + calls.length * 10,
    fetcher: async (url, init) => {
      running += 1;
      if (running > 1) overlapped = true;
      calls.push({ url: new URL(url), headers: init.headers });
      await Promise.resolve();
      running -= 1;
      const next = responses.shift();
      if (!next) throw new Error("unexpected request");
      return next;
    },
  });
  return { source, calls, sleeps, overlapped: () => overlapped };
}

test("search returns four allowed images, skips disallowed ones, and a reload continues without repeats", async () => {
  const first = [page("A", 1), page("B", 2, { meta: { LicenseShortName: "CC BY-SA 4.0" } }), page("C", 3), page("D", 4), page("E", 5), page("F", 6)];
  const { source, calls } = fakeSource([answer(first, 20)]);
  const one = await source.search({ target: "harbour boats", cursor: "", exclude: new Set(), count: 4 });
  assert.deepEqual(one.candidates.map((c) => c.id), ["File:A.jpg", "File:C.jpg", "File:D.jpg", "File:E.jpg"]);
  assert.equal(one.nextCursor, "5", "resumes right after the fourth accepted image, so F is not lost");
  assert.equal(calls.length, 1);
  const query = calls[0].url.searchParams;
  assert.equal(query.get("gsrsearch"), "harbour boats filetype:bitmap");
  assert.equal(query.get("gsrnamespace"), "6");
  assert.equal(query.get("maxlag"), "5");
  assert.match(calls[0].headers["user-agent"], /^PapyrusNewsroomImagePicker\/1\.0 \(https:\/\/example\.test\/contact\)/);
  assert.equal(calls[0].url.origin, "https://commons.wikimedia.org");

  const second = fakeSource([answer([page("A", 1), page("F", 2), page("G", 3), page("H", 4), page("I", 5)], 40)]);
  const two = await second.source.search({ target: "harbour boats", cursor: "5", exclude: new Set(["File:A.jpg", "File:C.jpg"]), count: 4 });
  assert.deepEqual(two.candidates.map((c) => c.id), ["File:F.jpg", "File:G.jpg", "File:H.jpg", "File:I.jpg"]);
  assert.equal(second.calls[0].url.searchParams.get("gsroffset"), "5");
});

test("when a page has too few allowed images the source asks again, one request after another, and reports the end", async () => {
  const { source, calls, overlapped } = fakeSource([answer([page("A", 1)], 20), answer([page("B", 1), page("C", 2)])]);
  const result = await source.search({ target: "rare thing", cursor: "", exclude: new Set(), count: 4 });
  assert.deepEqual(result.candidates.map((c) => c.id), ["File:A.jpg", "File:B.jpg", "File:C.jpg"]);
  assert.equal(result.nextCursor, null, "no continue token means no more for this search");
  assert.equal(calls.length, 2);
  assert.equal(overlapped(), false, "requests are serial");
});

test("an empty target asks nothing; a repeated identical request is served from memory", async () => {
  const { source, calls } = fakeSource([answer([page("A", 1)])]);
  assert.deepEqual(await source.search({ target: " ?! ", cursor: "", exclude: new Set(), count: 4 }), { candidates: [], nextCursor: null });
  assert.equal(calls.length, 0);
  await source.search({ target: "same", cursor: "", exclude: new Set(), count: 4 });
  await source.search({ target: "same", cursor: "", exclude: new Set(), count: 4 });
  assert.equal(calls.length, 1);
});

test("a busy or rate-limited answer stops the search with a retry hint and never loops", async () => {
  const limited = fakeSource([new Response("slow down", { status: 429, headers: { "retry-after": "30" } })]);
  await assert.rejects(limited.source.search({ target: "x y", cursor: "", exclude: new Set(), count: 4 }), (error: unknown) => error instanceof SourceBusy && error.retryAfterSeconds === 30);
  const lagged = fakeSource([new Response(JSON.stringify({ error: { code: "maxlag" } }), { status: 200 })]);
  await assert.rejects(lagged.source.search({ target: "x y", cursor: "", exclude: new Set(), count: 4 }), SourceBusy);
  assert.equal(limited.calls.length + lagged.calls.length, 2);
});

test("lookup re-reads one file by title and refuses anything that is no longer allowed or not a file title", async () => {
  const good = fakeSource([answer([page("A", 0)])]);
  assert.equal((await good.source.lookup("File:A.jpg"))?.creator, "Ana & Bo Example");
  assert.equal(good.calls[0].url.searchParams.get("titles"), "File:A.jpg");
  const changed = fakeSource([answer([page("A", 0, { meta: { LicenseShortName: "CC BY-SA 4.0" } })])]);
  assert.equal(await changed.source.lookup("File:A.jpg"), null);
  assert.equal(await good.source.lookup("Main Page|File:B.jpg"), null);
  assert.equal(good.calls.length, 1);
});

// ---- search target --------------------------------------------------------------------------------------------------------------------

test("with no target the search words come from the title first, then the summary's repeated words", () => {
  assert.equal(deriveSearchTarget("How offshore wind farms are changing fishing towns", "Offshore wind projects reshape harbours. Fishing crews and harbours adapt to wind turbines."), "offshore wind farms changing harbours");
  assert.equal(deriveSearchTarget("", "Solar roofs and solar farms; solar storage."), "Solar roofs farms storage");
  assert.equal(deriveSearchTarget("The new report", "It says what is new."), "", "nothing distinctive: the editor types their own");
  assert.ok(deriveSearchTarget("a ".repeat(30) + "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta", "").split(" ").length <= 5);
});

// ---- picture checks -------------------------------------------------------------------------------------------------------------------

function png(width: number, height: number): Uint8Array {
  const bytes = new Uint8Array(33);
  bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52]);
  new DataView(bytes.buffer).setUint32(16, width);
  new DataView(bytes.buffer).setUint32(20, height);
  return bytes;
}
function jpeg(width: number, height: number): Uint8Array {
  return Uint8Array.from([0xff, 0xd8, 0xff, 0xe0, 0, 4, 0, 0, 0xff, 0xc0, 0, 11, 8, height >> 8, height & 255, width >> 8, width & 255, 3, 0, 0, 0]);
}
function webp(width: number, height: number): Uint8Array {
  const bytes = new Uint8Array(32);
  bytes.set([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50, 0x56, 0x50, 0x38, 0x58]);
  const w = width - 1, h = height - 1;
  bytes.set([w & 255, (w >> 8) & 255, (w >> 16) & 255, h & 255, (h >> 8) & 255, (h >> 16) & 255], 24);
  return bytes;
}

test("picture bytes are checked by their own content, not by a header or a name", () => {
  assert.deepEqual({ ...readPicture(png(1280, 853)) }, { kind: "png", extension: "png", mediaType: "image/png", width: 1280, height: 853, bytes: 33 });
  assert.equal(readPicture(jpeg(1280, 853)).mediaType, "image/jpeg");
  assert.equal(readPicture(jpeg(1280, 853)).height, 853);
  assert.equal(readPicture(webp(1600, 900)).width, 1600);
  assert.throws(() => readPicture(new Uint8Array()), PictureRefused);
  assert.throws(() => readPicture(Uint8Array.from([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0, 0, 0, 0])), /not a JPEG/);
  assert.throws(() => readPicture(new TextEncoder().encode("<svg xmlns='http://www.w3.org/2000/svg'></svg>")), /not a JPEG/);
  assert.throws(() => readPicture(png(120, 90)), /only 120 px wide/);
  assert.throws(() => readPicture(new Uint8Array(4_500_001).fill(1)), /too large/);
  assert.throws(() => readPicture(Uint8Array.from([0xff, 0xd8, 0xff, 0xe0, 0, 2, 0, 0])), /size could not be read/);
});

// ---- the editor-only route ------------------------------------------------------------------------------------------------------------

async function identityFixture() {
  const { privateKey, publicKey } = await generateKeyPair("RS256");
  const jwk = { ...(await exportJWK(publicKey)), kid: "fixture", alg: "RS256", use: "sig" };
  const cache = new SimpleJwksCache({ fetcher: { fetch: async () => ({ keys: [jwk] }) } as never });
  const pool = "us-east-1_Fixture";
  const issuer = `https://cognito-idp.us-east-1.amazonaws.com/${pool}`;
  const sign = (claims: Record<string, unknown> = {}) => new SignJWT({ sub: "editor-a", token_use: "access", client_id: "newsroom-client", "cognito:groups": ["editor"], ...claims })
    .setProtectedHeader({ alg: "RS256", kid: "fixture" }).setIssuer(issuer).setExpirationTime("5m").sign(privateKey);
  return { sign, resolveIdentity: newsroomChatIdentityResolver({ user_pool_id: pool, user_pool_client_id: "newsroom-client" }, cache) };
}

const post = (body: unknown, token?: string) => new NextRequest("https://publication.example/api/newsroom/stock-images", {
  method: "POST", headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(body),
});

test("the route answers only a verified editor or admin, and never reaches the source otherwise", async () => {
  const { sign, resolveIdentity } = await identityFixture();
  let reached = 0;
  const source = { id: "fake", label: "Fake", imageHosts: ["upload.wikimedia.org"], search: async () => { reached += 1; return { candidates: [], nextCursor: null }; }, lookup: async () => { reached += 1; return null; } };
  const ask = (request: NextRequest) => handleStockImageRequest(request, { resolveIdentity, source });
  const body = { action: "search", target: "harbour", cursor: "", exclude: [] };
  assert.equal((await ask(post(body))).status, 401, "no token");
  assert.equal((await ask(post(body, "not-a-token"))).status, 401);
  assert.equal((await ask(post(body, await sign({ "cognito:groups": ["reader"] })))).status, 401, "a signed-in reader is refused");
  assert.equal((await ask(post(body, await sign({ "cognito:groups": [] })))).status, 401);
  assert.equal((await ask(post(body, await sign({ token_use: "id" })))).status, 401);
  assert.equal((await ask(post(body, await sign({ client_id: "other" })))).status, 401);
  assert.equal(reached, 0);
  assert.equal((await ask(post(body, await sign()))).status, 200, "editor");
  assert.equal((await ask(post(body, await sign({ "cognito:groups": ["admin"] })))).status, 200, "admin");
  assert.equal(reached, 2);
  assert.equal((await ask(new NextRequest("https://publication.example/api/newsroom/stock-images"))).status, 405);
  assert.equal((await ask(post({ action: "search", target: "  " }, await sign()))).status, 400);
  assert.equal((await ask(post({ action: "delete" }, await sign()))).status, 400);
});

test("a pick is looked up at the source, copied only from the source's own address, checked, and handed back with its size", async () => {
  const { sign, resolveIdentity } = await identityFixture();
  const found = candidateFromPage(page("Harbour", 1));
  assert.ok("candidate" in found);
  const candidate = found.candidate;
  const fetched: string[] = [];
  const source = { id: "fake", label: "Fake", imageHosts: ["upload.wikimedia.org"], search: async () => ({ candidates: [], nextCursor: null }), lookup: async (id: string) => (id === candidate.id ? candidate : null) };
  const withBytes = (bytes: Uint8Array, status = 200) => ({
    resolveIdentity, source,
    fetcher: async (url: string) => { fetched.push(url); return new Response(bytes as BodyInit, { status, headers: { "content-type": "image/jpeg" } }); },
  });
  const token = await sign();
  const good = await handleStockImageRequest(post({ action: "image", id: candidate.id, url: "https://evil.example/steal.jpg" }, token), withBytes(jpeg(1280, 853)));
  assert.equal(good.status, 200);
  assert.equal(good.headers.get("content-type"), "image/jpeg");
  assert.equal(good.headers.get("x-stock-width"), "1280");
  assert.equal(good.headers.get("x-stock-picked-by"), "editor-a");
  assert.deepEqual(fetched, [candidate.imageUrl], "the browser's address is ignored");
  assert.equal((await handleStockImageRequest(post({ action: "image", id: "File:Gone.jpg" }, token), withBytes(jpeg(1280, 853)))).status, 404);
  assert.equal((await handleStockImageRequest(post({ action: "image", id: candidate.id }, token), withBytes(new TextEncoder().encode("<html>")))).status, 422);
  assert.equal((await handleStockImageRequest(post({ action: "image", id: candidate.id }, token), withBytes(png(300, 200)))).status, 422);
  assert.equal((await handleStockImageRequest(post({ action: "image", id: candidate.id }, token), withBytes(new Uint8Array(), 503))).status, 503);
  const offHost = { ...source, lookup: async () => ({ ...candidate, imageUrl: "https://evil.example/x.jpg" }) };
  assert.equal((await handleStockImageRequest(post({ action: "image", id: candidate.id }, token), { ...withBytes(jpeg(1280, 853)), source: offHost })).status, 502);
  const redirecting = { resolveIdentity, source, fetcher: async () => new Response(null, { status: 302, headers: { location: "https://evil.example/x.jpg" } }) };
  assert.equal((await handleStockImageRequest(post({ action: "image", id: candidate.id }, token), redirecting)).status, 502, "a redirect off the allowed hosts is refused");
});

// ---- the cover as saved text ----------------------------------------------------------------------------------------------------------

const candidate = (() => {
  const result = candidateFromPage(page("Harbour", 1));
  assert.ok("candidate" in result);
  return result.candidate;
})();
const record = coverRecord(candidate, "assets/my-story/harbour.jpg", "2026-11-05T12:00:00.000Z", "editor-a");

test("the front matter gets the cover path and a structured record, and loses the Night counterpart of the old picture", () => {
  const before = "title: My story\nimage: /assets/old/diagram.png\nimageDark: /assets/old/diagram.dark.png\nseededImage:\n  url: https://other.example/p.jpg\n  hosted: false\n";
  const after = frontMatterWithCover(before, record);
  assert.match(after, /^image: \/assets\/my-story\/harbour\.jpg$/m);
  assert.doesNotMatch(after, /imageDark|seededImage|diagram/);
  assert.match(after, /title: My story/);
  const read = readCoverRecord(after);
  assert.equal(read?.creator, "Ana & Bo Example");
  assert.equal(read?.licence, "CC BY 4.0");
  assert.equal(read?.licenceUrl, "https://creativecommons.org/licenses/by/4.0");
  assert.equal(read?.sourceUrl, "https://commons.wikimedia.org/wiki/File:Harbour.jpg");
  assert.equal(read?.pickedBy, "editor-a");
  assert.equal(frontMatterWithCover("", record).includes("coverImage:"), true);
  assert.throws(() => frontMatterWithCover("title: [unclosed", record), /front matter has an error/);
  assert.equal(readCoverRecord("title: x\n"), null);
});

test("the body gets the credited figure first; an earlier stock cover or seeded picture is replaced in place; a diagram is left alone", () => {
  const directive = coverDirective("assets/my-story/harbour.jpg", "A harbour", creditLine(candidate));
  assert.equal(directive, '::image{src="assets/my-story/harbour.jpg" alt="A harbour" credit="Image: Ana & Bo Example, CC BY 4.0, via Wikimedia Commons"}');
  const diagram = '::image{src="assets/my-story/diagram.png" alt="Diagram" layout="wide"}';
  assert.equal(bodyWithCover(`${diagram}\n\nText.\n`, directive, []), `${directive}\n\n${diagram}\n\nText.\n`);
  assert.equal(bodyWithCover("", directive, []), `${directive}\n`);
  const earlier = '::image{src="assets/my-story/old.jpg" alt="Old" credit="Image: Someone"}';
  assert.equal(bodyWithCover(`${earlier}\n\n${diagram}\n\nText.\n`, directive, ["assets/my-story/old.jpg"]), `${directive}\n\n${diagram}\n\nText.\n`);
  assert.deepEqual(replaceableCoverSources("coverImage:\n  srcPath: assets/a/b.jpg\nseededImage:\n  url: https://x.example/y.jpg\n"), ["assets/a/b.jpg", "https://x.example/y.jpg"]);
  assert.deepEqual(replaceableCoverSources("title: x"), []);
  assert.equal(bodyWithCover('::image{alt="x" credit="}"}\nText', directive, ["z"]).startsWith(directive), true);
  assert.equal(coverDirective("a.jpg", 'say "hi" {x}', 'a "b" {c}'), '::image{src="a.jpg" alt="say hi x" credit="a b c"}');
});

// ---- the picker's states --------------------------------------------------------------------------------------------------------------

const noop = () => undefined;
function view(overrides: Partial<PickerViewProps>): string {
  return renderToStaticMarkup(createElement(CoverImagePickerView, {
    status: "loaded", candidates: [], targetText: "", searched: "offshore wind", searchedFromStory: true, error: null, hasMore: true, pickingId: null, pickError: null,
    onTargetChange: noop, onSearch: noop, onReload: noop, onRetry: noop, onPick: noop, onClose: noop, ...overrides,
  }));
}

test("the picker shows four options with their credit, Accept, Reload and Give up, and a text box with a Search button", () => {
  const html = view({ candidates: [0, 1, 2, 3].map(demoCandidate) });
  assert.equal(html.match(/data-stock-candidate=/g)?.length, 4);
  assert.equal(html.match(/data-stock-accept/g)?.length, 4);
  assert.equal(html.match(/data-stock-credit/g)?.length, 4, "each option shows its credit");
  assert.match(html, /Image: Example Creator 1, CC BY 4\.0, via Wikimedia Commons/);
  assert.match(html, /Image: Example Creator 3, Public domain, via Wikimedia Commons/);
  assert.match(html, /Accept as cover/);
  assert.match(html, /Reload: four more/);
  assert.match(html, /Give up/);
  assert.match(html, /Searched for <q>offshore wind<\/q>, worked out from the title and summary/);
  assert.match(html, /<input[^>]*data-stock-target/);
  assert.match(html, /data-stock-search/);
  assert.doesNotMatch(html, /<select|role="combobox"|<option/);
  const ownClasses = [...html.matchAll(/<(?:section|div|ul|li|p|a|img|form|span)\b[^>]*\bclass="([^"]*)"/g)].map((match) => match[1]).join(" ");
  assert.doesNotMatch(ownClasses, /\bborder|\bdivide|\bring-|\boutline/, "no borders, rules or outlines for structure");
  assert.match(html, /<input[^>]*border-transparent/, "the text box is a flat field");
  assert.match(html, /<svg[^>]*lucide/, "Lucide icons");
});

test("loading, nothing found, failure and no-more each say so in words and keep the typed text", () => {
  const loading = view({ status: "loading", targetText: "my words" });
  assert.match(loading, /Looking on Wikimedia Commons/);
  assert.match(loading, /value="my words"/);
  assert.match(loading, /data-stock-search="" disabled|disabled=""[^>]*data-stock-search/);
  const empty = view({ status: "empty", searched: "zzqx", searchedFromStory: false });
  assert.match(empty, /Nothing found for <q>zzqx<\/q> with a licence we can use \(public domain, CC0 and CC BY\)/);
  const failed = view({ status: "error", error: "The image source is busy. Try again in a minute.", targetText: "my words" });
  assert.match(failed, /role="alert"/);
  assert.match(failed, /busy\. Try again in a minute\. What you typed is kept\./);
  assert.match(failed, /value="my words"/);
  assert.match(failed, /Try again/);
  const end = view({ candidates: [demoCandidate(0)], hasMore: false });
  assert.match(end, /No more results for this search/);
  const picking = view({ candidates: [demoCandidate(0), demoCandidate(1)], pickingId: demoCandidate(0).id });
  assert.match(picking, /Copying in…/);
  assert.equal(picking.match(/data-stock-accept=""[^>]*disabled|disabled=""[^>]*data-stock-accept/g)?.length, 2, "both Accept buttons wait while one copies");
  assert.match(view({ pickError: "That image could not be copied in." }), /data-stock-pick-error/);
  assert.match(view({ status: "empty", searched: "" }), /no title or summary/);
});

test("the preview source never repeats an option and can run out", async () => {
  const client = createDemoStockImageClient(0);
  const seen = new Set<string>();
  let cursor: string | null = "";
  while (cursor !== null) {
    const result: Awaited<ReturnType<typeof client.search>> = await client.search({ target: "x", cursor, exclude: [...seen] });
    for (const item of result.candidates) {
      assert.ok(!seen.has(item.id));
      seen.add(item.id);
    }
    cursor = result.nextCursor;
  }
  assert.equal(seen.size, 40);
});
