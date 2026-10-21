import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { compileRedirectFunctionSource, edgeRulesFromSettings } from "../amplify/publication/redirect-rules";

const source = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), "../amplify/publication/redirect-and-index.js"),
  "utf8",
);

type EdgeResponse = { statusCode?: number; headers?: { location: { value: string } }; uri?: string };

/** Runs the CloudFront Function source against an in-memory key value store. */
async function run(rules: ReturnType<typeof edgeRulesFromSettings>, store: Record<string, string>, uri: string): Promise<EdgeResponse> {
  const compiled = compileRedirectFunctionSource(source, rules)
    .replace('import cf from "cloudfront";', "")
    .concat("\nreturn handler;");
  const handler = new Function("cf", compiled)({ kvs: () => ({ get: async (key: string) => store[key] }) });
  return handler({ request: { uri } });
}

const settings = {
  urls: { style: "directory" },
  redirects: {
    patterns: [
      { pattern: "^/blog/page/(\\d+)/$", to: "/articles/page/$1/" },
      { pattern: "^/blog/([^/]+)/$", to: "/articles/$1/", status: 301 },
      { pattern: "^/biased-decisions/.*$", to: "/" },
    ],
  },
};
const rules = edgeRulesFromSettings(settings);

// The same table is asserted from Python in procedures/newsroom/tests/test_standard_frontend_redirects.py.
const cases: [string, string | null][] = [
  ["/blog/page/3/", "/articles/page/3/"],
  ["/blog/hello/", "/articles/hello/"],
  ["/biased-decisions/a/b", "/"],
  ["/articles/hello.html", "/articles/hello/"],
  ["/404.html", null],
  ["/articles/hello/", null],
];

for (const [uri, expected] of cases) {
  test(`pattern redirect ${uri}`, async () => {
    const response = await run(rules, {}, uri);
    if (expected === null) {
      assert.equal(response.statusCode, undefined);
    } else {
      assert.equal(response.statusCode, 301);
      assert.equal(response.headers?.location.value, expected);
    }
  });
}

test("an exact redirect in the store wins over a pattern", async () => {
  const response = await run(rules, { "/blog/hello/": "/elsewhere/" }, "/blog/hello/");
  assert.equal(response.headers?.location.value, "/elsewhere/");
});

test("with no rules the source is unchanged and plain paths still get an index document", async () => {
  assert.equal(compileRedirectFunctionSource(source, []), source);
  assert.equal((await run([], {}, "/about/")).uri, "/about/index.html");
});
