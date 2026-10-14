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
| `anth-us.yaml` | `papyrus-edge-anth-us` (rollback) | The retired Anth.us Amplify reader. Updating the stack with this template moves the origin back, and only works while the Amplify reader app exists |

Update a stack with a change set, never in place, and read the change set before executing it.

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
