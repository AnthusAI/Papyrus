import { PROJECTION_TYPES_ENV } from "./site-story-types";

/**
 * The publication's time zone, an IANA name such as `America/New_York`, from the site's projection.json (`publication.timeZone`). `withPapyrus` copies it into
 * NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES with the Story types. Scheduling is on for a site that sets it: every scheduled time is shown and picked in this zone,
 * and a site without it has no schedule fields, panel or page. A name the browser does not know is an error, not a reason to show another zone.
 */
export function publicationTimeZone(environment: Record<string, string | undefined> = process.env): string | null {
  // Next inlines only a literal `process.env.NEXT_PUBLIC_*` access in browser code, so the default read names the variable.
  const text = environment === process.env ? process.env.NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES : environment[PROJECTION_TYPES_ENV];
  if (!text) return null;
  const zone = (JSON.parse(text) as { publication?: { timeZone?: unknown } }).publication?.timeZone;
  if (zone === undefined || zone === null) return null;
  if (typeof zone !== "string" || !zone) throw new Error(`publication.timeZone is a time zone name such as 'America/New_York', not ${JSON.stringify(zone)}.`);
  try { new Intl.DateTimeFormat("en-US", { timeZone: zone }); } catch { throw new Error(`publication.timeZone '${zone}' is not a time zone name this browser knows.`); }
  return zone;
}
