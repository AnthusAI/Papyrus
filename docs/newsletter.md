# Newsletter

Status: signup capture is Live. Sending infrastructure is Live for Shipped. Sending itself is Not built yet.

## What exists

A site can collect newsletter signups. There are two paths. Both only store the address.

### The signup plugin

The `signup` plugin ([plugins.md](plugins.md)) adds a `SignupEntry` model, one guest operation (`submitSignup`), a web component and a "Signups" panel in the newsroom.

- Enable it in the site's `papyrus.config.ts` with `backend: { plugins: ["signup"] }`. The default form is `newsletter`.
- Put the component on a page: `<papyrus-signup form="newsletter" endpoint="..." identity-pool="..."></papyrus-signup>` with the version 1 signup script from `/_plugins/`. The attributes are described in [plugins.md](plugins.md).
- The function checks the address, applies a honeypot field and a minimum fill time, and counts requests per address and identity. A web ACL rate limit is on by default.
- The entry id is a hash of the form and the lower-cased address, so a repeat signup changes nothing.
- Editors and admins read entries; guests cannot read anything.

### The public form endpoint

The built-in public form endpoint ([public-forms.md](public-forms.md)) accepts a post with form id `newsletter` and an `email`. It creates a `Message` with `messageKind: form_submission` and `messageType: newsletter_signup` (`amplify/functions/public-forms/core.ts`). Only editors and admins can read these Messages.

## Listing signups

- Plugin entries: the Signups panel in the newsroom.
- Public form messages: `papyrus messages list --kind form_submission --form newsletter`. Add `--status all` to include handled ones and `--json` for machine output. `papyrus messages handle` marks one handled. See [public-forms.md](public-forms.md).

Email addresses are personal data. Treat them like subscriber records.

## What does not happen today

- No confirmation email is sent. Neither the signup plugin nor the public form endpoint sends any email.
- There is no double opt-in, no unsubscribe link, no issue composer and no sending.

## Not built yet

Initiative PPY-31455f plans sending. Its milestones, none of them built:

- M1 (PPY-08dbd8): Amazon SES per site, double opt-in, one-click unsubscribe.
- M2 (PPY-19a098): issues composed, approved by an editor and sent once.
- M3 (PPY-024f96): automation and alerts.
- M4 (PPY-df1d54): hardening.

## Sending stack

Status: Live for Shipped (PPY-874ad4).

Each site that will send newsletters gets its own CloudFormation stack, `papyrus-newsletter-sending-<siteId>`, from `infra/newsletter/papyrus-newsletter-sending.yaml`. It creates the SES identity for the sending domain with Easy DKIM and a custom MAIL FROM domain, the DNS records for them and for DMARC, a configuration set `papyrus-<siteId>` without open or click tracking, and an SNS topic `papyrus-newsletter-events-<siteId>` that carries delivery events. The stack for Shipped sends from `shipped.anth.us`; its identity, DKIM and MAIL FROM checks all pass.

The stack does not send mail and does not lift the SES sandbox. Parameters, the deploy command, verification checks and teardown are in `infra/newsletter/README.md`.
