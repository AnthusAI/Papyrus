export type InboundEmailSettings = {
  domain: string;
  corpusKey: string;
  publicSiteBaseUrl: string;
  /** Only a site whose stack verifies the SES domain identity needs a hosted zone. */
  dnsZone?: { id: string; name: string };
};

function required(environment: Record<string, string | undefined>, name: string, why: string): string {
  const value = (environment[name] ?? "").trim();
  if (value === "") throw new Error(`Inbound email is enabled but ${name} is not set. ${why}`);
  return value;
}

/**
 * Every inbound email setting is the site's own; none has a default. A missing one stops the synth and names itself.
 * Called only when the site turns inbound email on.
 */
export function resolveInboundEmailSettings(
  environment: Record<string, string | undefined>,
  options: { manageDomainIdentity: boolean },
): InboundEmailSettings {
  const settings: InboundEmailSettings = {
    domain: required(environment, "PAPYRUS_INBOUND_EMAIL_DOMAIN", "It is the domain that receives mail, for example mail.example.org.").toLowerCase(),
    corpusKey: required(environment, "PAPYRUS_INBOUND_EMAIL_CORPUS_KEY", "It is the corpus that received mail is filed into."),
    publicSiteBaseUrl: required(environment, "PAPYRUS_PUBLIC_SITE_BASE_URL", "It is the site's public https origin, linked from reply emails."),
  };
  if (options.manageDomainIdentity) {
    settings.dnsZone = {
      id: required(environment, "PAPYRUS_ROUTE53_HOSTED_ZONE_ID", "The stack writes the SES verification record into this hosted zone."),
      name: required(environment, "PAPYRUS_ROUTE53_HOSTED_ZONE_NAME", "It is the DNS name of that hosted zone.").replace(/\.$/, ""),
    };
  }
  return settings;
}

export function inboundDnsRecordName(domain: string, zoneName: string): string {
  return domain.endsWith(`.${zoneName}`) ? domain.slice(0, -(zoneName.length + 1)) : domain;
}
