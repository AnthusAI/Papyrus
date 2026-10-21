/**
 * The browser origins a site's public forms accept: the site's own public hosts, never a wildcard.
 * Pure so that `scripts/test-public-forms.ts` can pin it.
 */
export type PublicFormsOriginSources = {
  /** `publicForms.allowedOrigins` in the site's backend config: always honoured (https, or localhost for development). */
  explicit?: readonly string[];
  /** Public hosts the site is served from: distribution aliases, the reader domain. Bare hosts become https origins. */
  hosts?: readonly (string | undefined)[];
  /** URLs whose origin is the site's own: the revalidate base URL, the sign-in redirect URLs. https only, never localhost. */
  urls?: readonly (string | undefined)[];
};

function httpsOrigin(value: string): string | undefined {
  try {
    const url = new URL(value.includes("://") ? value : `https://${value}`);
    return url.protocol === "https:" && url.hostname !== "localhost" ? url.origin : undefined;
  } catch {
    return undefined;
  }
}

export function derivePublicFormOrigins(sources: PublicFormsOriginSources): string[] {
  const origins = new Set<string>();
  for (const value of sources.explicit ?? []) {
    try {
      const url = new URL(value);
      if (url.protocol === "https:" || (url.protocol === "http:" && url.hostname === "localhost")) origins.add(url.origin);
      else throw new Error("not allowed");
    } catch {
      throw new Error(`publicForms.allowedOrigins entry ${JSON.stringify(value)} must be an https origin (or http://localhost).`);
    }
  }
  for (const host of sources.hosts ?? []) {
    const origin = host === undefined || host.trim() === "" ? undefined : httpsOrigin(host.trim());
    if (origin !== undefined) origins.add(origin);
  }
  for (const value of sources.urls ?? []) {
    const origin = value === undefined || value.trim() === "" ? undefined : httpsOrigin(value.trim());
    if (origin !== undefined) origins.add(origin);
  }
  return [...origins].sort();
}
