import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import {
  INTERIM_SUBJECT_PATTERN,
  READER_DEV_SECRET_ENV,
  SITE_SUBJECT_PATTERN,
  interimSubject,
  interimSubjectsAllowed,
  readerIsStaff,
  readerSubject,
} from "../lib/reader-subject";

const siteSubject = `ss1_${"A".repeat(43)}`;
const devSecret = "development-only-secret-0123456789";
const developmentEnvironment = { SITE_ENV: "development", [READER_DEV_SECRET_ENV]: devSecret };
const personId = "person-global-id-123";
const session = (changes: Record<string, unknown> = {}) => ({ personId, accessToken: "x.y.z", accessTokenExpiresAt: 2_000_000_000, ...changes });

assert.equal(readerSubject(null, developmentEnvironment), null, "signed out");
assert.equal(readerSubject(undefined, developmentEnvironment), null);

const productionEnvironments = [
  { SITE_ENV: "production" },
  { SITE_ENV: "production", [READER_DEV_SECRET_ENV]: devSecret },
  { SITE_ENV: "staging", [READER_DEV_SECRET_ENV]: devSecret },
  { SITE_ENV: "development", NODE_ENV: "production", [READER_DEV_SECRET_ENV]: devSecret },
  { NODE_ENV: "production", [READER_DEV_SECRET_ENV]: devSecret },
  {},
  { [READER_DEV_SECRET_ENV]: devSecret },
];
for (const environment of productionEnvironments) {
  assert.equal(readerSubject(session(), environment), null, `no siteSubject outside development: ${JSON.stringify(Object.keys(environment))} ${environment.SITE_ENV}`);
  assert.equal(readerSubject(session({ siteSubject }), environment), siteSubject, "a real siteSubject is used everywhere");
  assert.equal(interimSubjectsAllowed(environment), false);
}

for (const bad of ["", "ss1_short", `ss1_${"A".repeat(44)}`, `ss2_${"A".repeat(43)}`, `ssdev_${"A".repeat(43)}`, personId, "reader@example.test", `ss1_${"A".repeat(42)}!`]) {
  assert.equal(readerSubject(session({ siteSubject: bad }), { SITE_ENV: "production" }), null, `rejects a malformed siteSubject: ${bad}`);
  assert.equal(readerSubject(session({ siteSubject: bad }), developmentEnvironment)?.startsWith("ssdev_"), true, "development falls back to the interim value, never to the bad one");
}
assert.equal(SITE_SUBJECT_PATTERN.test(siteSubject), true);

const interim = readerSubject(session(), developmentEnvironment) as string;
assert.match(interim, INTERIM_SUBJECT_PATTERN);
assert.equal(interim, `ssdev_${createHmac("sha256", devSecret).update(personId).digest("base64url")}`);
assert.equal(interim, interimSubject(personId, devSecret), "stable per person");
assert.notEqual(interim, interimSubject("another-person", devSecret));
assert.notEqual(interim, interimSubject(personId, "another-development-secret-0123456"));
assert.equal(interim.includes(personId), false, "the person id is not recoverable from the interim value");
assert.equal(readerSubject(session(), { SITE_ENV: "test", [READER_DEV_SECRET_ENV]: devSecret })?.startsWith("ssdev_"), true);
assert.equal(readerSubject(session(), { SITE_ENV: "development", [READER_DEV_SECRET_ENV]: "short" }), null, "a short dev secret is refused");
assert.equal(readerSubject(session({ siteSubject }), developmentEnvironment), siteSubject, "a real siteSubject wins in development");

const claims = (groups: unknown) => `h.${Buffer.from(JSON.stringify({ "cognito:groups": groups })).toString("base64url")}.s`;
assert.equal(readerIsStaff({ accessToken: claims(["editor"]) }), true);
assert.equal(readerIsStaff({ accessToken: claims(["reader", "admin"]) }), true);
assert.equal(readerIsStaff({ accessToken: claims(["reader"]) }), false);
assert.equal(readerIsStaff({ accessToken: claims("editor") }), false);
assert.equal(readerIsStaff({ accessToken: claims([]) }), false);
assert.equal(readerIsStaff({ accessToken: "not-a-jwt" }), false);
assert.equal(readerIsStaff({ accessToken: "a.@@@.c" }), false);
assert.equal(readerIsStaff(null), false);

console.log("reader subject ok");
