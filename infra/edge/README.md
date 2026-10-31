# Edge distributions

CloudFormation templates of the hand-run `papyrus-edge-<site>` stacks that front a site. They were kept outside git until PPY-84cce3; these are the deployed versions.

| Template | Stack | Origin |
| --- | --- | --- |
| `pilobol-us.yaml` | `papyrus-edge-pilobol-us` | Pilobol.us S3 projection bucket (OAC), with the directory-index and redirect function |
| `anth-us-s3.yaml` | `papyrus-edge-anth-us` | Anth.us S3 projection bucket (OAC), redirect and header functions |
| `threat-intelligence.yaml` | `papyrus-edge-threat-intelligence` | The Threat Intelligence Amplify app (main and staging distributions). The deployed version, kept as a rollback reference |
| `threat-intelligence-media.yaml` | `papyrus-edge-threat-intelligence` (proposed) | Same stack plus a `/api/media/media/*` behavior that serves the media bucket through an origin access control. Not deployed. See `docs/video-loading.md` |
| `threat-intelligence-reader-cache.yaml` | `papyrus-edge-threat-intelligence` (proposed) | The deployed template plus a `ReaderPagesCachePolicy` on the main distribution's default behavior (honours the origin `s-maxage` and `stale-while-revalidate`, keys on the Next RSC headers, ignores cookies and query strings). `/newsroom*`, `/api/*` and `/_next/image*` keep CachingDisabled. The staging distribution is unchanged because staging serves drafts. Not deployed (PPY-79e668) |
| `p-apyr-us-reader-cache.yaml` | `papyrus-edge-p-apyr-us` (proposed) | The same change for the p.apyr.us production distribution. Not deployed (PPY-79e668) |
| `../../docs/hosting/p-apyr-us-edge.yaml` | `papyrus-edge-p-apyr-us` (proposed) | The full intended p.apyr.us edge: the stack's own production and staging distributions, plus the two live distributions that sit outside the stack today (`E17ZRAI87DN065` marketing, `E2EM0JLBC2W9WW` reader) and the `papyrus-reader-edge` function. The reader function only redirects `/newsroom` to the CMS host and forwards the host header; the legacy `/information` redirect function is gone and the marketing default behavior uses the stack's forward-host function for the apex redirect. Not deployed |
| `s3-projection-cms.yaml` | `papyrus-edge-<site>` (reference) | An S3 projection bucket (OAC) on the default behavior and the site's CMS Amplify app on `/newsroom*`, `/_next/*`, `/api/*`, `/cli/*` and `/.well-known/papyrus-cli.json`, on one host. The shape of the Shipped, Distinctive Mark, DataParade and Threat Intelligence edges. Carries the 404 handling described below |
| `anth-us.yaml` | `papyrus-edge-anth-us` (rollback) | The retired Anth.us Amplify reader. Updating the stack with this template moves the origin back, and only works while the Amplify reader app exists |

Update a stack with a change set, never in place, and read the change set before executing it.

## The 404 page and the CMS behaviors

CloudFront `CustomErrorResponses` are distribution-wide: they cannot be scoped to one cache behavior. A distribution that maps 403 and 404 to `/404.html` (the S3 projection answers a missing key with 403) therefore also replaces every 403 and 404 that the CMS origin sends on `/api/*`, `/newsroom*` and `/_next/*` with the site's 404 page. The visible damage: a same-origin rejection from `/api/newsletter/subscribe` (403 JSON) showed the 404 page, and `/api/reader/*` and `/api/auth/prospectus/*` had the same exposure.

A distribution with CMS behaviors must have **no** `CustomErrorResponses`. `s3-projection-cms.yaml` serves the 404 page from the default behavior instead, with a Lambda@Edge `origin-response` function associated with the default behavior only:

- The function runs when the S3 origin answers 403 or 404 (an origin response that CloudFront has not cached). Any other status passes through untouched.
- It fetches `/404.html` from the distribution's own domain and rewrites the S3 response in place: status 404, that body, `Content-Type: text/html`. It keeps the other response headers, because CloudFront answers 502 (`LambdaValidationError`) when a function drops a read-only header such as `Transfer-Encoding`, which a freshly built response does. If that fetch fails, or `/404.html` itself is missing, it returns a plain `Not found` with status 404, so a miss never loops.
- CloudFront caches the generated 404 under the default error-caching TTL (10 seconds) for that URL, as the error responses did. The page is fetched through the distribution, so it passes through the default behavior's viewer-response function, if the stack has one, like any other page.
- The CMS behaviors have no origin-response function, so their statuses and bodies reach the client as the origin sent them.

Why Lambda@Edge, not a CloudFront Function: a CloudFront Function cannot read or fetch the response body, and the styled 404 page is an object in the bucket. The function is cheap: it runs only on a cache miss that S3 answers with 403 or 404.

Changing the function code needs a new immutable version: edit the `Description` of `NotFoundPageVersion` along with the code. The version resources are `Retain`, because Lambda cannot delete a replicated version for some hours after it is detached. Apply to an existing stack with a change set: the diff must show the removal of `CustomErrorResponses` and the addition of the role, function, version and the default behavior's `LambdaFunctionAssociations`, and nothing else.

A pure S3 distribution without CMS behaviors (`anth-us-s3.yaml`, `pilobol-us.yaml`, the distribution the site backend creates) has nothing to mask, and keeps its error responses.

## The console on its own host

A site can serve its newsroom console from a separate host (`newsroom.<site host>`). That host gets its own small distribution: one default behavior to the site's CMS Amplify app, uncached, all methods, the `x-forwarded-host` viewer-request function, no S3 origin and no `CustomErrorResponses`. The stack creates its own ACM certificate (DNS validation in the Route 53 zone) and the alias records, so no Amplify domain association is needed, which matters where `create-domain-association` is throttled. The Shipped template is `infra/edge/shipped-console.yaml` in Shipped-web. The site's app-shell `site.json` names the host as `cms.consoleOrigin`.

## New sites

A new Markus site does not need one of these. Set `backend.publication.distribution` in `papyrus.config.ts` and the site backend creates the distribution:

```ts
publication: {
  kind: "s3-projection",
  distribution: { create: true, aliases: ["example.org"], acm: { hostedZoneId: "Z...", hostedZoneName: "example.org" } },
}
```

- `acm` creates a DNS-validated certificate in us-east-1 and writes the validation CNAME records itself. That works only when the hosted zone is in the same AWS account as the backend.
- When the zone lives in another account, create the certificate by hand in us-east-1 (ACM, DNS validation), add the CNAME records ACM shows (`_<token>.<name>` pointing at `_<token>.acm-validations.aws.`) in the account that owns the zone, wait for the status `Issued`, and pass `certificateArn` instead of `acm`.
- After the first deploy, add an alias record (A and AAAA, alias to the distribution's `*.cloudfront.net` name) for each alias name in the zone. Papyrus never writes DNS records outside the account it deploys to.
- Without `aliases` the distribution answers on its `*.cloudfront.net` name, which is enough for a first look.

## Proposed change sets (unexecuted, need approval)

Reader page caching needs Papyrus `1.0.0-next.52` or later on the site (origin sends `s-maxage=60, stale-while-revalidate=60` on prebuilt reader pages). Create, read, then execute (account 712236451410, `AWS_PROFILE=papyrus-production`):

```bash
aws cloudformation create-change-set --stack-name papyrus-edge-threat-intelligence --change-set-name reader-cache --template-body file://infra/edge/threat-intelligence-reader-cache.yaml --parameters ParameterKey=CertificateArn,UsePreviousValue=true --capabilities CAPABILITY_IAM --region us-east-1
aws cloudformation describe-change-set --stack-name papyrus-edge-threat-intelligence --change-set-name reader-cache --region us-east-1

aws cloudformation create-change-set --stack-name papyrus-edge-p-apyr-us --change-set-name reader-cache --template-body file://infra/edge/p-apyr-us-reader-cache.yaml --parameters ParameterKey=CertificateArn,UsePreviousValue=true ParameterKey=AmplifyAppId,UsePreviousValue=true ParameterKey=ProductionHost,UsePreviousValue=true ParameterKey=StagingHost,UsePreviousValue=true ParameterKey=ApexHost,UsePreviousValue=true --capabilities CAPABILITY_IAM --region us-east-1
aws cloudformation describe-change-set --stack-name papyrus-edge-p-apyr-us --change-set-name reader-cache --region us-east-1
```

Expected change set: one added `AWS::CloudFront::CachePolicy`, and a modify of the main (production) distribution only. Roll back by updating the stack with `threat-intelligence.yaml` or the previously deployed p.apyr.us template. Media: `threat-intelligence-media.yaml` follows `docs/video-loading.md`; it ships after the Papyrus backend deploy that adds the CloudFront statement to the media bucket policy.

## p.apyr.us edge: adopting the two live distributions

`docs/hosting/p-apyr-us-edge.yaml` expects an IMPORT change set first, because `E17ZRAI87DN065`, `E2EM0JLBC2W9WW` and `papyrus-reader-edge` already exist. The import carries the live (legacy) definitions; the update that follows moves them to the template's definitions. Both steps are read-before-execute, in account 712236451410:

1. Import: resources `MarketingDistribution` (`E17ZRAI87DN065`), `ReaderDistribution` (`E2EM0JLBC2W9WW`) and `ReaderEdgeFunction` (`papyrus-reader-edge`). An import change set can contain no other change, so the template given to it holds these three resources exactly as live (legacy function code, legacy function association on the marketing distribution).
2. Update with `docs/hosting/p-apyr-us-edge.yaml`: replaces the reader function code, swaps the marketing distribution's `papyrus-legacy-reader-redirect` association for `ForwardHostFunction`, and leaves everything else unchanged. Afterwards delete the `papyrus-legacy-reader-redirect` function, which nothing references.

Expected diff in step 2: `ReaderEdgeFunction` code, one `FunctionAssociations` entry on `MarketingDistribution`'s default behavior. Nothing is replaced.

The p.apyr.us site runs this adoption from its own Amplify build with `papyrus-infra deploy-edge`. A template parameter the live stack does not have yet takes its template default, so adding a parameter never blocks the change set.
