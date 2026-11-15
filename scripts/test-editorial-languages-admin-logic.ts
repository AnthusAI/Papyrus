import assert from "node:assert/strict";
import test from "node:test";
import { checkAfter, setPrefix, setPublic, setSlugPolicy, settleLanguages, type LanguagesCheck, type SiteLanguages } from "../lib/editorial-languages-form";

const MOM: SiteLanguages = { primary: "en", enabled: ["en", "es-419", "zh-Hans"], futureKey: { kept: true } } as SiteLanguages;

test("making a language public lists the primary first and keeps every other key", () => {
  const next = setPublic(MOM, "es-419", true);
  assert.deepEqual(next.public, ["en", "es-419"]);
  assert.deepEqual((next as Record<string, unknown>).futureKey, { kept: true });
  assert.deepEqual(next.enabled, MOM.enabled);
});

test("making the last non-primary language not public removes the list, which means only the primary", () => {
  const made = setPublic(setPublic(MOM, "es-419", true), "zh-Hans", true);
  assert.deepEqual(made.public, ["en", "es-419", "zh-Hans"]);
  assert.deepEqual(setPublic(made, "es-419", false).public, ["en", "zh-Hans"]);
  assert.equal("public" in setPublic(setPublic(MOM, "es-419", true), "es-419", false), false);
});

test("a prefix is set for one language and a blank one returns it to the default", () => {
  const next = setPrefix(setPrefix(MOM, "es-419", " latam "), "zh-Hans", "zh");
  assert.deepEqual(next.prefixes, { "es-419": "latam", "zh-Hans": "zh" });
  assert.deepEqual(setPrefix(next, "es-419", "").prefixes, { "zh-Hans": "zh" });
  assert.equal("prefixes" in setPrefix(setPrefix(MOM, "es-419", "x"), "es-419", "  "), false);
});

test("a slug policy is set for one language and the default option removes it", () => {
  const next = setSlugPolicy(MOM, "zh-Hans", "pinyin");
  assert.deepEqual(next.slugs, { "zh-Hans": "pinyin" });
  assert.equal("slugs" in setSlugPolicy(next, "zh-Hans", ""), false);
});

test("settling drops what names a language that is no longer enabled and keeps the rest", () => {
  const stored = {
    ...MOM, public: ["en", "es-419", "zh-Hans"], prefixes: { "es-419": "latam", "zh-Hans": "zh" }, slugs: { "zh-Hans": "pinyin", "es-419": "primary" },
  } as SiteLanguages;
  const settled = settleLanguages({ ...stored, enabled: ["en", "es-419"] });
  assert.deepEqual(settled.public, ["en", "es-419"]);
  assert.deepEqual(settled.prefixes, { "es-419": "latam" });
  assert.deepEqual(settled.slugs, { "es-419": "primary" });
  assert.deepEqual((settled as Record<string, unknown>).futureKey, { kept: true });
});

test("settling leaves a setting that names only valid languages exactly as it is", () => {
  const stored = { ...MOM, public: ["en", "es-419"], prefixes: { "es-419": "es" }, slugs: { "es-419": "translated" } } as SiteLanguages;
  assert.deepEqual(settleLanguages(stored), stored);
});

test("a new primary is listed first in the public list and loses its own serving keys", () => {
  const stored = { primary: "es-419", enabled: ["en", "es-419"], public: ["en", "es-419"], prefixes: { en: "en", "es-419": "es" } } as SiteLanguages;
  const settled = settleLanguages(stored);
  assert.deepEqual(settled.public, ["es-419", "en"]);
  assert.deepEqual(settled.prefixes, { en: "en" });
});

test("a language list with nothing public beyond the primary settles to no public list", () => {
  assert.equal("public" in settleLanguages({ ...MOM, public: ["en", "fr"], enabled: ["en", "es-419"] } as SiteLanguages), false);
});

test("a refusal keeps the last rows so the field that caused it can be corrected", () => {
  const ok: LanguagesCheck = checkAfter({ status: "checking", rows: [] }, {
    ok: true, primary: "en", enabled: ["en", "es-419"],
    languages: [{ tag: "es-419", primary: false, public: false, prefix: "es", defaultPrefix: "es", slugPolicy: "translated", defaultSlugPolicy: "translated" }],
  });
  const refused = checkAfter(ok, { ok: false, message: "languages.prefixes: es-419 and en would both be served under /en/." });
  assert.equal(refused.status, "refused");
  assert.equal(refused.rows.length, 1);
  assert.match(refused.message ?? "", /would both be served/);
});
