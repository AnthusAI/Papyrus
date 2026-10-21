import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { compileRedirectFunctionSource, edgeRulesFromSettings, negotiatesMarkdown } from "../amplify/publication/redirect-rules";

const source = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), "../amplify/publication/redirect-and-index.js"),
  "utf8",
);

type EdgeResponse = { statusCode?: number; headers?: { location: { value: string } }; uri?: string };
type Run = { negotiateMarkdown?: boolean; accept?: string };

/** Runs the CloudFront Function source against an in-memory key value store. */
async function run(rules: ReturnType<typeof edgeRulesFromSettings>, store: Record<string, string>, uri: string, options: Run = {}): Promise<EdgeResponse> {
  const compiled = compileRedirectFunctionSource(source, rules, { negotiateMarkdown: options.negotiateMarkdown })
    .replace('import cf from "cloudfront";', "")
    .concat("\nreturn handler;");
  const handler = new Function("cf", compiled)({ kvs: () => ({ get: async (key: string) => store[key] }) });
  const headers = options.accept === undefined ? {} : { accept: { value: options.accept } };
  return handler({ request: { uri, headers } });
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
  ["/about", "/about/"],
  ["/articles/hello", "/articles/hello/"],
  ["/404", null],
  ["/", null],
  ["/index.html", null],
  ["/articles/index.html", null],
  ["/articles/page/2/index.html", null],
  ["/myindex.html", "/myindex/"],
  ["/sitemap.xml", null],
  ["/_plugins/papyrus-search.js", null],
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

test("the 404 page is reachable at /404", async () => {
  assert.equal((await run(rules, {}, "/404")).uri, "/404.html");
});

test("with no rules the source is unchanged and plain paths still get an index document", async () => {
  assert.equal(compileRedirectFunctionSource(source, []), source);
  assert.equal((await run([], {}, "/about/")).uri, "/about/index.html");
});

const MARKDOWN_CASES: [string, string | undefined, boolean, string][] = [
  ["/about/", "text/markdown", true, "/about/index.md"],
  ["/about/", "text/markdown, text/html;q=0.5", true, "/about/index.md"],
  ["/", "text/markdown", true, "/index.md"],
  ["/articles/x.html", "text/markdown;q=0.9, text/html;q=0.8", true, "/articles/x.md"],
  ["/about/", "text/html, text/markdown;q=0.5", true, "/about/index.html"],
  ["/about/", "text/html,application/xhtml+xml,*/*;q=0.8", true, "/about/index.html"],
  ["/about/", "*/*", true, "/about/index.html"],
  ["/about/", "text/markdown;q=0", true, "/about/index.html"],
  ["/about/", undefined, true, "/about/index.html"],
  ["/404.html", "text/markdown", true, "/404.html"],
  ["/feed.xml", "text/markdown", true, "/feed.xml"],
  ["/css/site.css", "text/markdown", true, "/css/site.css"],
  ["/about/", "text/markdown", false, "/about/index.html"],
];

for (const [uri, accept, negotiate, expected] of MARKDOWN_CASES) {
  test(`markdown negotiation ${uri} Accept=${accept} enabled=${negotiate}`, async () => {
    const response = await run([], {}, uri, { negotiateMarkdown: negotiate, accept });
    assert.equal(response.uri, expected);
  });
}

test("a site opts into negotiation by being a standard front end site unless it turns markdown off", () => {
  assert.equal(negotiatesMarkdown({ site: { name: "x" } }), true);
  assert.equal(negotiatesMarkdown({ site: { name: "x" }, agents: { markdown: false } }), false);
  assert.equal(negotiatesMarkdown({}), false);
});
