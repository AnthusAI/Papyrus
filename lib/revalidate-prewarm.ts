export const PREWARM_ORIGIN_ENV = "PAPYRUS_PREWARM_ORIGIN";
export const PREWARM_CONCURRENCY = 4;
export const PREWARM_MAX_PATHS = 40;
export const PREWARM_TIMEOUT_MILLISECONDS = 25_000;
export const PREWARM_REQUEST_HEADER = "x-papyrus-prewarm";

export type PrewarmFetch = (url: string, init: { headers: Record<string, string>; signal: AbortSignal; redirect: "manual" }) => Promise<{ status: number }>;

export type PrewarmResult = {
  path: string;
  status: number | null;
  milliseconds: number;
};

export function resolvePrewarmOrigin(requestUrl: string, environment: Record<string, string | undefined> = process.env): string {
  const configured = environment[PREWARM_ORIGIN_ENV]?.trim();
  if (configured) return configured.replace(/\/+$/, "");
  return new URL(requestUrl).origin;
}

export async function prewarmPaths(
  origin: string,
  paths: string[],
  options: { fetchPage?: PrewarmFetch; now?: () => number } = {},
): Promise<PrewarmResult[]> {
  const fetchPage = options.fetchPage ?? (fetch as unknown as PrewarmFetch);
  const now = options.now ?? Date.now;
  const queue = [...new Set(paths)].filter((path) => path.startsWith("/")).slice(0, PREWARM_MAX_PATHS);
  const results: PrewarmResult[] = [];

  async function worker(): Promise<void> {
    for (let path = queue.shift(); path !== undefined; path = queue.shift()) {
      const startedAt = now();
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), PREWARM_TIMEOUT_MILLISECONDS);
      try {
        const response = await fetchPage(`${origin}${path}`, {
          headers: { [PREWARM_REQUEST_HEADER]: "1" },
          signal: controller.signal,
          redirect: "manual",
        });
        results.push({ path, status: response.status, milliseconds: now() - startedAt });
      } catch {
        results.push({ path, status: null, milliseconds: now() - startedAt });
      } finally {
        clearTimeout(timer);
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(PREWARM_CONCURRENCY, queue.length) }, worker));
  return results;
}
