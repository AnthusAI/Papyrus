# Newsletter sending stack

`papyrus-newsletter-sending.yaml` creates the Amazon SES sending setup for one site (PPY-874ad4). It is a CloudFormation stack in the production account, us-east-1. Per-site stacks are hand-run with the command below; the operator stack `papyrus-newsletter-sending-operators` deploys from the release (`infra/pipeline/README.md`). Use one stack per site, named `papyrus-newsletter-sending-<siteId>`.

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
| EventTransport | sns | `sns` (the per-site topic), `eventbridge` (the account's default bus, no topic) or `both`. Sites keep `sns` until they turn on notifications and then use `both`; the operator stack uses `eventbridge`. |

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

The SNS topic carries the Prospectus cost tags. `CostAccount` defaults to `owner` (Prospectus charges whichever Account holds the `papyrus-<SiteId>` entitlement); the operator stack passes `shared`.

### Operator stack: notify.anth.us (PPY-bf63d5)

Deployed by the release (PPY-b8cc79): its parameters live in `infra/pipeline/stacks.json` and the zone is looked up at deploy time. The command below is the same thing by hand, kept for reference; do not run it.

Operator mail (CloudWatch alarm emails, `docs/operator-alerts.md`) sends from the `alerts` mailbox of notify.anth.us with configuration set `papyrus-operators`, from the same template. The anth.us zone is in the same account, so there is no delegation. Look the zone's id up rather than copying it:

```bash
ZONE=$(aws route53 list-hosted-zones --query 'HostedZones[?Name==`anth.us.`].Id' --output text | sed 's|/hostedzone/||')
aws cloudformation deploy \
  --template-file infra/newsletter/papyrus-newsletter-sending.yaml \
  --stack-name papyrus-newsletter-sending-operators \
  --parameter-overrides SiteId=operators SendingDomain=notify.anth.us HostedZoneId="$ZONE" EventTransport=eventbridge CostAccount=shared \
  --tags papyrus:site=operators papyrus:feature=operator-alerts \
  --no-fail-on-empty-changeset
```

On 2026-11-04 a read-only listing showed no record containing `notify` in the zone, so DKIM (`<token>._domainkey.notify.anth.us`), `bounce.notify.anth.us` (MX, SPF) and `_dmarc.notify.anth.us` collide with nothing. The apex `anth.us` publishes no `_dmarc` record (a separate gap; this stack only creates the subdomain's). With `EventTransport=eventbridge` there is no SNS topic, and delivery events arrive on the default bus as `Email Delivered`, `Email Bounced` and so on. Open and click events are never enabled, and a test fails if either appears.

Before the first deploy, list the zone's records for the sending domain and make sure none collide with the DKIM, MAIL FROM and `_dmarc` names.

### Sites that send notifications (PPY-c522bf)

A site's notifications function sends from this stack's identity and configuration set (`docs/notifications.md`, "Sending as the site"). [newsletter-sending-identities.json](../config/newsletter-sending-identities.json) says which sites have a stack. For each site that will send notifications, a person with the production profile does, after reading the change set:

1. Sites with no stack yet (Anth.us and Threat Intelligence on 2026-11-04): run the deploy command above with the site's `SiteId`, `SendingDomain` and zone, adding `EventTransport=both`, then set the site's `sendingDomain` in `newsletter-sending-identities.json` and the postal address parameter.
2. Sites with a stack: re-run the same command with the stack's existing parameters plus `EventTransport=both`. The change adds one EventBridge event destination (`eventbridge-events`) to the configuration set and nothing else; the SNS topic and its destination stay as they are.
3. `aws sesv2 get-email-identity --email-identity <domain>` still reads `True SUCCESS SUCCESS`, and `aws sesv2 get-configuration-set-event-destinations --configuration-set-name papyrus-<siteId>` lists `sns-events`, `eventbridge-events` and `cloudwatch-metrics`.

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
