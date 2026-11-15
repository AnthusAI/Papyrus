import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, "../amplify/publication/redirect-and-index.js"), "utf8");
assert.match(source, /^import cf from "cloudfront";/m);

function loadHandler(redirects) {
  const fakeCloudFront = {
    kvs: () => ({
      get: async (key) => {
        if (!(key in redirects)) throw new Error("KeyNotFound");
        return redirects[key];
      },
    }),
  };
  const executable = source.replace(/^import cf from "cloudfront";\n/m, "");
  return new Function("cf", `${executable}\nreturn handler;`)(fakeCloudFront);
}

const handler = loadHandler({
  "/old-post/": "/articles/new-post/",
  "/legacy": "https://example.org/elsewhere",
  "/zh/posts/%E6%96%87/": "/zh/%E5%8A%A8%E6%80%81/%E6%96%87/",
});
const viewerRequest = (uri) => ({ request: { uri, headers: {} } });

const redirected = await handler(viewerRequest("/old-post/"));
assert.equal(redirected.statusCode, 301);
assert.equal(redirected.headers.location.value, "/articles/new-post/");

const redirectedToUrl = await handler(viewerRequest("/legacy"));
assert.equal(redirectedToUrl.statusCode, 301);
assert.equal(redirectedToUrl.headers.location.value, "https://example.org/elsewhere");

// A redirect keeps the query string, and the encoded address of a Chinese page matches its encoded key.
const withQuery = await handler({ request: { uri: "/zh/posts/%E6%96%87/", headers: {}, querystring: { utm: { value: "x" }, a: { value: "" } } } });
assert.equal(withQuery.statusCode, 301);
assert.equal(withQuery.headers.location.value, "/zh/%E5%8A%A8%E6%80%81/%E6%96%87/?utm=x&a");
const absoluteWithQuery = await handler({ request: { uri: "/legacy", headers: {}, querystring: { q: { value: "1" } } } });
assert.equal(absoluteWithQuery.headers.location.value, "https://example.org/elsewhere");

assert.equal((await handler(viewerRequest("/"))).uri, "/index.html");
assert.equal((await handler(viewerRequest("/articles/a-post/"))).uri, "/articles/a-post/index.html");
assert.equal((await handler(viewerRequest("/articles/a-post"))).uri, "/articles/a-post/index.html");
assert.equal((await handler(viewerRequest("/404"))).uri, "/404.html");
assert.equal((await handler(viewerRequest("/sitemap.xml"))).uri, "/sitemap.xml");
assert.equal((await handler(viewerRequest("/assets/app.css"))).uri, "/assets/app.css");
assert.equal((await handler(viewerRequest("/tags/c.s/"))).uri, "/tags/c.s/index.html");

console.log("redirect-and-index function ok");
