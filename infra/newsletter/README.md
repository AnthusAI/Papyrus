# Newsletter sending stack

`papyrus-newsletter-sending.yaml` creates the Amazon SES sending setup for one site (PPY-874ad4). It is a hand-run CloudFormation stack in account 712236451410, us-east-1, like the stacks in `infra/monitoring`. Use one stack per site, named `papyrus-newsletter-sending-<siteId>`.

## What it creates

- An SES email identity for the sending domain, with Easy DKIM (RSA 2048) and a custom MAIL FROM domain (`bounce.<domain>` by default).
- Route 53 records in the site's zone: three DKIM CNAMEs, the MAIL FROM MX and SPF TXT, and an optional `_dmarc` TXT record (no reporting address).
- An SES configuration set named `papyrus-<siteId>`: reputation metrics on, sending on, bounces and complaints suppressed, no open or click tracking.
- An SNS topic `papyrus-newsletter-events-<siteId>` that receives send, delivery, bounce, complaint, reject, rendering failure and delivery delay events, and a CloudWatch destination for send, bounce and complaint counts.

## Parameters

| Name | Default | Meaning |
| --- | --- | --- |
| SiteId | none | Lower-case site id used in names. |
| SendingDomain | none | Domain the site sends from. |
| HostedZoneId | none | Route 53 zone that serves the domain. |
| MailFromSubdomain | bounce | Label for the MAIL FROM domain. |
| DmarcPolicy | quarantine | `none`, `quarantine` or `reject`. |
| CreateDmarcRecord | true | Set `false` if the domain already publishes DMARC. |

## Deploy

```bash
export AWS_PROFILE=papyrus-production AWS_REGION=us-east-1
test "$(aws sts get-caller-identity --query Account --output text)" = 712236451410
aws cloudformation deploy \
  --template-file infra/newsletter/papyrus-newsletter-sending.yaml \
  --stack-name papyrus-newsletter-sending-shipped \
  --parameter-overrides SiteId=shipped SendingDomain=shipped.anth.us HostedZoneId=Z04979341DPRV5BDQNZMG \
  --tags papyrus:site=shipped papyrus:feature=newsletter \
  --no-fail-on-empty-changeset
```

Before the first deploy, list the zone's records for the sending domain and make sure none collide with the DKIM, MAIL FROM and `_dmarc` names.

## Check verification

```bash
aws sesv2 get-email-identity --email-identity shipped.anth.us \
  --query '[VerifiedForSendingStatus,DkimAttributes.Status,MailFromAttributes.MailFromDomainStatus]' --output text
```

All three should read `True SUCCESS SUCCESS`. It usually takes a few minutes and can take up to about 30. You can also run `dig TXT _dmarc.<domain> +short`, `dig TXT bounce.<domain> +short` and `dig MX bounce.<domain> +short`.

A new SES account is in the sandbox until production access is granted; request it separately.

## Tear down

```bash
aws cloudformation delete-stack --stack-name papyrus-newsletter-sending-shipped
```

This removes the identity, configuration set, topic and DNS records. Do it only when the site stops sending.
