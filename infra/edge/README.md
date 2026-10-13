# Edge distributions

CloudFormation templates of the hand-run `papyrus-edge-<site>` stacks that front a site. They were kept outside git until PPY-84cce3; these are the deployed versions.

| Template | Stack | Origin |
| --- | --- | --- |
| `pilobol-us.yaml` | `papyrus-edge-pilobol-us` | Pilobol.us S3 projection bucket (OAC), with the directory-index and redirect function |
| `anth-us-s3.yaml` | `papyrus-edge-anth-us` | Anth.us S3 projection bucket (OAC), redirect and header functions |
| `threat-intelligence.yaml` | `papyrus-edge-threat-intelligence` | The Threat Intelligence Amplify app (main and staging distributions). The deployed version, kept as a rollback reference |
| `threat-intelligence-media.yaml` | `papyrus-edge-threat-intelligence` (proposed) | Same stack plus a `/api/media/media/*` behavior that serves the media bucket through an origin access control. Not deployed. See `docs/video-loading.md` |
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
