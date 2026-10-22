import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import {
  READER_POLL_SECRET_HEADER,
  handleReaderRetiredSubjects,
  resetReaderPollSecretCache,
  type ReaderRetirementRouteOptions,
} from "../lib/reader-retirement-route";
import { ProspectusAccountsError, ProspectusSiteAccounts, type ProspectusRequest } from "../lib/prospectus-site-identity";

const siteOrigin = "https://reader.example.test";
const pollSecret = "the poll value used only by these tests";
const subject = (letter: string) => `ss1_${letter.repeat(43)}`;
const page = {
  retired: [
    { siteSubject: subject("A"), reason: "deleted", retiredAt: "2026-10-21T14:00:00Z" },
    { siteSubject: subject("B"), reason: "merged", survivingSiteSubject: subject("C"), retiredAt: "2026-10-21T14:00:00Z" },
  ],
  cursor: "next-cursor",
  more: true,
};

function harness(response: unknown = page, environment: Record<string, string> = { PAPYRUS_SITE_ORIGIN: siteOrigin, PAPYRUS_READER_POLL_SECRET_PARAMETER: "/papyrus/reader/poll" }) {
  const requests: ProspectusRequest[] = [];
  let secretReads = 0;
  const options: ReaderRetirementRouteOptions = {
    environment,
    readSecret: async () => { secretReads += 1; return pollSecret; },
    resolveRuntime: async () => ({
      accounts: new ProspectusSiteAccounts(async (request) => {
        requests.push(request);
        if (response instanceof Error) throw response;
        return response;
      }),
    }),
  };
  return { options, requests, secretReads: () => secretReads };
}

function request(path: string, headers: Record<string, string> = {}): NextRequest {
  return new NextRequest(new URL(path, siteOrigin), { headers });
}
const authorized = { [READER_POLL_SECRET_HEADER]: pollSecret };

(async () => {
  {
    const { options, requests, secretReads } = harness();
    const answer = await handleReaderRetiredSubjects(request("/api/reader/retired?since=abc", authorized), options);
    assert.equal(answer.status, 200);
    assert.equal(answer.headers.get("cache-control"), "no-store");
    assert.deepEqual(await answer.json(), page, "the page is passed through");
    assert.deepEqual(requests.map((entry) => [entry.method, entry.path]), [["GET", "/v1/accounts/site-subjects/retired?since=abc"]]);
    assert.equal(requests[0].humanAccessToken, undefined, "the call is the site's own, with no person's token");
    await handleReaderRetiredSubjects(request("/api/reader/retired", authorized), options);
    assert.equal(requests[1].path, "/v1/accounts/site-subjects/retired", "no cursor on the first poll");
    assert.equal(secretReads(), 1, "the secret is cached");
    resetReaderPollSecretCache();
  }

  for (const headers of [{} as Record<string, string>, { [READER_POLL_SECRET_HEADER]: "wrong" }, { [READER_POLL_SECRET_HEADER]: pollSecret + "x" }, { authorization: `Bearer ${pollSecret}` }]) {
    const { options, requests } = harness();
    const answer = await handleReaderRetiredSubjects(request("/api/reader/retired", headers), options);
    assert.equal(answer.status, 401, JSON.stringify(headers));
    assert.deepEqual(Object.keys(await answer.json()).sort(), ["error", "message"]);
    assert.equal(requests.length, 0, "Prospectus is not called without the secret");
    resetReaderPollSecretCache();
  }

  {
    const { options, requests } = harness(page, { PAPYRUS_SITE_ORIGIN: siteOrigin });
    const answer = await handleReaderRetiredSubjects(request("/api/reader/retired", authorized), options);
    assert.equal(answer.status, 503, "a site without the secret parameter is closed");
    assert.equal(requests.length, 0);
    resetReaderPollSecretCache();
    const unreadable = await handleReaderRetiredSubjects(request("/api/reader/retired", authorized), { ...harness().options, readSecret: async () => { throw new Error("denied"); } });
    assert.equal(unreadable.status, 503, "an unreadable secret never opens the route");
    resetReaderPollSecretCache();
  }

  for (const path of ["/api/reader/retired?since=a%20b", "/api/reader/retired?since=" + "x".repeat(513), "/api/reader/retired?other=1", "/api/reader/retired?since=a&since2=b"]) {
    const { options, requests } = harness();
    assert.equal((await handleReaderRetiredSubjects(request(path, authorized), options)).status, 400, path);
    assert.equal(requests.length, 0);
    resetReaderPollSecretCache();
  }

  {
    const refused = harness(new ProspectusAccountsError(403, "reader_route_forbidden", "Editor sites cannot poll."));
    const answer = await handleReaderRetiredSubjects(request("/api/reader/retired", authorized), refused.options);
    assert.equal(answer.status, 502);
    assert.deepEqual(await answer.json(), { error: "reader_route_forbidden", message: "Editor sites cannot poll." });
    resetReaderPollSecretCache();
    const down = harness(new Error("network"));
    assert.equal((await handleReaderRetiredSubjects(request("/api/reader/retired", authorized), down.options)).status, 502);
    resetReaderPollSecretCache();
    const malformed = harness(new ProspectusAccountsError(400, "invalid_cursor", "Bad cursor."));
    assert.equal((await handleReaderRetiredSubjects(request("/api/reader/retired?since=zzz", authorized), malformed.options)).status, 400);
    resetReaderPollSecretCache();
  }

  {
    const noOrigin = harness(page, { PAPYRUS_READER_POLL_SECRET_PARAMETER: "/papyrus/reader/poll" });
    assert.equal((await handleReaderRetiredSubjects(request("/api/reader/retired", authorized), noOrigin.options)).status, 503);
    resetReaderPollSecretCache();
  }

  console.log("reader retirement route ok");
})();
