/** Email belongs to a cloud site, independently of any newsletter plugin. */
export type CloudEmailConfig = {
  mode: "managed" | "existing";
  sendingDomain: string;
  senderLocalPart: string;
  configurationSet: string;
  eventTopicName: string;
};

export function parseCloudEmail(raw: unknown, cloud: boolean, siteId: string): CloudEmailConfig | undefined {
  if (!cloud) {
    if (raw !== undefined) throw new Error("site.json: email requires a cloud cms; static-only sites do not need email resources");
    return undefined;
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("site.json: email is required for cloud sites; configure mode managed or existing and an explicit sendingDomain (see docs/email-reference-intake.md)");
  }
  const value = raw as Record<string, unknown>;
  for (const key of Object.keys(value)) {
    if (!["mode", "sendingDomain", "senderLocalPart", "configurationSet", "eventTopicName"].includes(key)) {
      throw new Error(`site.json: email.${key} is not a known field`);
    }
  }
  if (value.mode !== "managed" && value.mode !== "existing") throw new Error("site.json: email.mode must be managed or existing");
  const string = (key: string, pattern: RegExp, fallback?: string) => {
    const result = value[key] ?? fallback;
    if (typeof result !== "string" || !pattern.test(result)) throw new Error(`site.json: email.${key} is required and must be valid`);
    return result;
  };
  return {
    mode: value.mode,
    sendingDomain: string("sendingDomain", /^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/),
    senderLocalPart: string("senderLocalPart", /^[a-z0-9][a-z0-9._+-]{0,63}$/, "notifications"),
    configurationSet: string("configurationSet", /^[A-Za-z0-9_-]{1,64}$/, value.mode === "managed" ? `papyrus-${siteId}` : undefined),
    // Preserve the newsletter consumer's historical default; the topic now also serves notifications.
    eventTopicName: string("eventTopicName", /^[A-Za-z0-9_-]{1,256}$/, value.mode === "managed" ? `papyrus-newsletter-events-${siteId}` : undefined),
  };
}

