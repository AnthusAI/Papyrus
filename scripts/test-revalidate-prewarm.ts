/**
 * The revalidate endpoint re-fetches the pages it just cleared.
 *
 *   npx tsx scripts/test-revalidate-prewarm.ts
 */
import {
  PREWARM_CONCURRENCY,
  PREWARM_MAX_PATHS,
  PREWARM_ORIGIN_ENV,
  PREWARM_REQUEST_HEADER,
  prewarmPaths,
  resolvePrewarmOrigin,
  type PrewarmFetch,
} from "../lib/revalidate-prewarm";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

async function main() {
  assert(resolvePrewarmOrigin("https://app.example/api/revalidate", {}) === "https://app.example", "origin defaults to the request origin");
  assert(
    resolvePrewarmOrigin("https://app.example/api/revalidate", { [PREWARM_ORIGIN_ENV]: "https://origin.example/" }) === "https://origin.example",
    "configured origin wins and loses its trailing slash",
  );

  const requested: string[] = [];
  let inFlight = 0;
  let peak = 0;
  const headers: Array<Record<string, string>> = [];
  const fetchPage: PrewarmFetch = async (url, init) => {
    inFlight += 1;
    peak = Math.max(peak, inFlight);
    requested.push(url);
    headers.push(init.headers);
    await new Promise((resolve) => setTimeout(resolve, 5));
    inFlight -= 1;
    return { status: url.endsWith("/boom") ? 500 : 200 };
  };

  const results = await prewarmPaths("https://o.example", ["/a", "/a", "/b", "relative", "/boom", "/c", "/d", "/e"], { fetchPage });
  assert(requested.length === 6, "duplicates and non-absolute paths are skipped");
  assert(requested.every((url) => url.startsWith("https://o.example/")), "every request targets the origin");
  assert(headers.every((header) => header[PREWARM_REQUEST_HEADER] === "1"), "prewarm requests are marked");
  assert(peak <= PREWARM_CONCURRENCY && peak > 1, "requests run in parallel up to the limit");
  assert(results.find((result) => result.path === "/boom")?.status === 500, "a failing page is reported with its status");

  const failing = await prewarmPaths("https://o.example", ["/x"], { fetchPage: async () => { throw new Error("network"); } });
  assert(failing[0].status === null, "a network failure is reported, not thrown");

  const many = Array.from({ length: PREWARM_MAX_PATHS + 10 }, (_, index) => `/p${index}`);
  const capped = await prewarmPaths("https://o.example", many, { fetchPage: async () => ({ status: 200 }) });
  assert(capped.length === PREWARM_MAX_PATHS, "the number of prewarmed paths is capped");

  console.log("PASS: revalidate prewarm");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
