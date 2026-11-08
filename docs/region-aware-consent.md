# Region-aware cookie consent

A Papyrus static site can stop showing the cookie notice to visitors who do not need it. It is off unless a site sets `chrome.consent_mode.region_lookup: true`; a site that does not opt in behaves exactly as before and shows the notice to every visitor without a stored choice.

This is a mechanism, not legal advice. Which regions need a notice is a decision for the site owner and their legal adviser.

## How it works

1. The page sets every consent signal to `denied` first, including `analytics_storage`, and issues the analytics configuration. It never waits for the network.
2. If the visitor has a stored choice (Accept or Reject), that choice is applied and nothing else happens: the lookup is skipped.
3. Otherwise the page makes one anonymous request to the site's own address (`/_papyrus/consent` by default) with a 1.5 second timeout and the banner stays hidden.
4. The edge answers `{"country": "DE", "notice": true}`.
   - `notice: false` with a two-letter country: the banner is never shown and the page sends `gtag('consent','update',{analytics_storage:'granted'})`. Advertising signals (`ad_storage`, `ad_user_data`, `ad_personalization`) stay denied until the visitor accepts, as in the site's standard; a "Cookie settings" link still opens the choices.
   - Anything else shows the banner and keeps everything denied.

### Fails closed

The banner is shown, and everything stays denied, when the answer is missing, slow, not JSON, not an object, has `notice` other than the boolean `false`, has no two-letter country (unknown), or when the request fails or the browser cannot make it. The decision is one pure function, `c.needsNotice(answer)`, in the page script. A choice the visitor makes while the lookup is pending always wins over the answer.

### Privacy

The country is read only to decide; it is not stored, logged or sent to analytics, and the page makes no third-party request. The edge answer is `private, no-store`.

## Regions that need a notice

`CONSENT_DENIED_BY_DEFAULT_REGIONS` in `src/papyrus_content/markus_renderer/consent.py` is the one definition: the EU 27, Iceland, Liechtenstein, Norway, the United Kingdom and Switzerland. It is a default policy choice that the owner or legal owns, not legal advice, and it must be reviewed. A site replaces it with `denied_by_default_regions` or adds to it with `additional_denied_by_default_regions`. The browser script, Google's `region` parameter and the edge function's list are all generated from it.

On the Google `region` parameter: without the lookup the site keeps using it, because it is how a regulated visitor is denied before any script runs. With the lookup on the global default already denies everything, so the region-scoped default would only repeat it and is omitted. The lookup is therefore stricter than today for unregulated visitors in one way: analytics wait for the answer (normally a few milliseconds from the edge) instead of starting granted.

## The edge answer

`infra/edge/consent-region-function.js` is a reference CloudFront Function (`cloudfront-js-2.0`, viewer-request). It is not deployed and not attached to any distribution. See `infra/edge/README.md` for the generator and test.

### Open question: is the country header visible to the function?

Not verified on our distributions. What the AWS documentation says: the `CloudFront-Viewer-Country` header is added only when a cache policy or origin request policy on the behavior includes it ([Add CloudFront request headers](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/adding-cloudfront-headers.html)): headers "to your origin or edge function", with a cache policy to include them in the cache key and an origin request policy to receive them without. The same page says `CloudFront-Viewer-Address`, `-ASN` and `-ISP` can go in an origin request policy but not a cache policy, and says nothing like that for the country header. The function event example lists `cloudfront-viewer-country` among the viewer-request headers ([event structure](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/functions-event-structure.html)). The documents do not say whether an origin request policy alone is enough for a viewer-request function, which runs before the origin request is built. Treat that as unknown until tested on a staging distribution: if only a cache policy works, the header becomes part of that behavior's cache key, which is harmless for a path whose response never comes from the origin.

### What each site's distribution would need (owner to review; nothing here changes a template)

- A cache behavior for the single path `/_papyrus/consent` (not the default behavior, so page caching is unaffected).
- A cache policy or origin request policy on that behavior that includes `CloudFront-Viewer-Country`.
- A viewer-request function association on it using the generated function.
- No origin is reached for that path, so the behavior needs a valid origin only because CloudFront requires one.

## Not covered

- IP geolocation is imperfect: VPNs, mobile carriers and corporate networks put visitors in the wrong country. A visitor with no resolvable country gets the banner.
- Other regimes (US state laws, Brazil and others) are for the owner and legal to decide; add them to the list if the notice is wanted there.
- The banner wording, a privacy policy and how long a choice is kept are unchanged and are the owner's.
