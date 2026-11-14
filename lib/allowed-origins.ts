export const CONSOLE_ORIGIN_ENV = "PAPYRUS_CONSOLE_ORIGIN";

type EnvironmentVariables = Record<string, string | undefined>;

/**
 * The origins whose pages may make same-origin requests: the public site origin and, when the newsroom console has its own host,
 * the console origin (PAPYRUS_CONSOLE_ORIGIN). A console origin that is not a canonical https origin is ignored, so a bad value
 * never widens the list.
 */
export function allowedOrigins(siteOrigin: string, environment: EnvironmentVariables = process.env): string[] {
  const configured = (environment[CONSOLE_ORIGIN_ENV] ?? "").trim();
  if (configured === "") return [siteOrigin];
  try {
    const parsed = new URL(configured);
    if (parsed.protocol === "https:" && parsed.origin === configured && configured !== siteOrigin) return [siteOrigin, configured];
  } catch {
    // An unparseable console origin allows nothing extra.
  }
  return [siteOrigin];
}

/** Whether a request's `Origin` header is exactly the site origin or the configured console origin. Null and "null" never match. */
export function isAllowedOrigin(origin: string | null, siteOrigin: string, environment: EnvironmentVariables = process.env): boolean {
  return origin !== null && allowedOrigins(siteOrigin, environment).includes(origin);
}
