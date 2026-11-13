import { useEffect, useState } from "react";
import { scheduleZone } from "./content-actions-client";
import { isLocalPreviewEnabled } from "./local-preview";

/** The sample publication's zone in the local preview, which has no backend to ask. */
export const LOCAL_PREVIEW_TIME_ZONE = "America/New_York";

let known: Promise<string | null> | undefined;

/**
 * The publication's time zone, as the backend reports it (the `schedule_settings` operation): one setting for one fact, so the badge, the picker, the calendar and
 * the DST refusals agree with how the backend reads a time. Asked once per page load. null when the site has not turned scheduling on; a failure to ask is an error
 * and the next call asks again.
 */
export function loadScheduleZone(): Promise<string | null> {
  if (isLocalPreviewEnabled()) return Promise.resolve(LOCAL_PREVIEW_TIME_ZONE);
  known ??= scheduleZone().then(result => result.enabled ? result.timeZone : null, reason => { known = undefined; throw reason; });
  return known;
}

/** `undefined` while loading, `null` when scheduling is off for this site, else the zone. A failure to ask is `error`. */
export function useScheduleZone(): { zone: string | null | undefined; error: string | null } {
  const [state, setState] = useState<{ zone: string | null | undefined; error: string | null }>({ zone: undefined, error: null });
  useEffect(() => {
    let current = true;
    loadScheduleZone().then(zone => { if (current) setState({ zone, error: null }); }, reason => { if (current) setState({ zone: undefined, error: reason instanceof Error ? reason.message : "The publication's time zone could not be read." }); });
    return () => { current = false; };
  }, []);
  return state;
}
