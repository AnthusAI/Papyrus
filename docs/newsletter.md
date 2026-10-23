# Newsletter

Status: signup capture is Live. Sending infrastructure is Live for Shipped. The `newsletter` plugin with double opt-in subscriptions is Built (PPY-949d68) and enabled on Shipped (shipped.anth.us: double opt-in, the `/newsletter/*` pages, the branded email theme, alerts and the weekly roundup) and on Distinctive (a weekly roundup and ruling alerts). Unsubscribe, preferences, erasure, bounce and complaint suppression and the pause alarms are Built too (PPY-b5a699), as are roundup issues, admin approval and paced sending (PPY-3ae3b9). Alerts (PPY-d415c0) and the newsroom panel (PPY-4005de) are Built.

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

- The signup plugin and the public form endpoint above send no email. Only the `newsletter` plugin (below) mails a confirmation.
- Only the `newsletter` plugin sends issues (see "Issues, approval and sending"). Nothing in the signup plugin or the public form endpoint does.

## Not built yet

Initiative PPY-31455f plans sending. Its milestones, with what is built:

- M1 (PPY-08dbd8): Amazon SES per site, double opt-in (built, see below), one-click unsubscribe.
- M2 (PPY-19a098): issues composed, approved by an admin and sent once (built, see below).
- M3 (PPY-024f96): automation and alerts (alerts: PPY-d415c0, see Alerts).
- M4 (PPY-df1d54): hardening.

## Email rendering

`papyrus_content.email_render` (pure Python, no network) turns Markus source into a responsive email: HTML with inline styles plus a plain-text alternative.

- `render_issue(subject=, markus=, theme=, footer=, preheader="", site_url=, list_name="")` renders a marketing issue. The footer carries the reason sentence, a manage link, an unsubscribe link, the site and the postal address. A blank address raises `PostalAddressMissing`. `EmailFooter.archive_url` (optional) adds an "All issues" link, in the HTML and the plain text,; the sender passes the list's `archivePath` under the site's base path, else the first roundup list's, else nothing. Without it the footer is unchanged. `list_name` (else the subject) is the label under the wordmark in a header band.
- `render_transactional(subject=, markus=, theme=, site_name=, site_url=, preheader="", action_url=None, action_label=None)` renders confirmation-style mail with a bulletproof button and a short footer. No address required.
- `theme_from_config(cfg, site_name)` builds an `EmailTheme` from the theme fields below.
- Markus runs with raw HTML disabled. Relative links and image sources become absolute against `site_url`; links with other schemes than http, https, mailto and tel are unlinked. A fixed tag-to-style map is inlined. The only `<style>` block holds a narrow-screen media query and a dark-mode override. No scripts, external CSS, web fonts or tracking pixels.
- Everything that is not Markus output (subject, preheader, footer fields) is escaped. The subject is collapsed to one line.
- Keep issues under 100 KB of HTML: Gmail clips at 102 KB. A test renders a long sample to guard the markup overhead.
- Preview: `poetry run python -m papyrus_content.email_render out.html` writes `out.html` and `out.txt` for a sample issue.

### Email theme fields

The `theme` block of the plugin config (`papyrus.config.ts`) is validated at synth time and again by `theme_from_config`. Colour and font values are CSS values: no `<`, `>`, `{`, `}`, `;`, quotes, backslash, backtick, `url(`, `expression(` or `@import`.

| Field | Meaning |
| --- | --- |
| `accent` (required) | Links, quote and callout rules, and the button fill unless `buttonFill` is set. |
| `text`, `background` (required) | Body text, and the page behind the email. |
| `surface`, `muted`, `fontFamily` | The content panel (default `#ffffff`), secondary text and rules (`#555555`), and the font stack. |
| `logoUrl` | An https image shown above the card in place of the site name, when there is no header band. |
| `headerBand`, `headerText` | A full-width band above the card holding the wordmark and, for issues, the list name in `labelFont`. `headerText` defaults to black or white, whichever reads on the band. |
| `buttonFill`, `buttonText`, `buttonBorder` | The bulletproof button: fill, label colour and a 1.5px border in this colour. Setting `buttonFill` or `buttonBorder` makes the button square with `11px 18px` padding and a 15px label; `buttonText` defaults to whichever of black or white reads on the fill. Without either the button is the plain rounded accent one. |
| `footerBand`, `footerText` | A band under the card with the wordmark, one mono line of underlined links (the site, All issues, Unsubscribe, Email preferences), the reason sentence and the postal address. |
| `wordmarkImageUrl`, `wordmarkAlt`, `wordmarkWidth`, `wordmarkHeight` | The brand mark as an image, since mail clients drop web fonts and `font-stretch`. The URL must be absolute https. Width and height (whole pixels, 1 to 2000, the size to display; supply a 2x image) are required with the URL and become `width` and `height` attributes. `wordmarkAlt` (default: the site name) is the image's alt text and the first line of the plain-text part. Without an image the bands show the site name as text. |
| `footerWordmarkWidth` | Optional. Draws the footer band's wordmark at this width (whole pixels, 1 to 400) instead of the header's size, reusing `wordmarkImageUrl` and its alt text; the height scales from `wordmarkWidth` and `wordmarkHeight`. About 110 gives a 26px-tall mark for a 168 by 40 wordmark. Needs `wordmarkImageUrl`. Setting it also switches the footer to the smaller design: plain mono lines (not uppercase) with the site named by its bare host (`shipped.anth.us`). Unset keeps the footer as it was. |
| `labelFont` | Font stack for the uppercase labels in the bands (default Menlo, Consolas, Courier New). |

A theme with none of the branding fields renders exactly as before (a test pins the markup). Links are always underlined and a button always has a text label, so nothing depends on colour. Dark mode, for a branded theme only: a `color-scheme: light dark` declaration and one `prefers-color-scheme: dark` block turn the page to `#1A1615`, the panels to `#26211F` and the text to `#F5F1EA`, while the bands and the button keep their own colours and text colours. Clients that invert colours themselves (some Gmail apps) may still shift a band.

## Sending stack

Status: Live for Shipped (PPY-874ad4).

Each site that will send newsletters gets its own CloudFormation stack, `papyrus-newsletter-sending-<siteId>`, from `infra/newsletter/papyrus-newsletter-sending.yaml`. It creates the SES identity for the sending domain with Easy DKIM and a custom MAIL FROM domain, the DNS records for them and for DMARC, a configuration set `papyrus-<siteId>` without open or click tracking, and an SNS topic `papyrus-newsletter-events-<siteId>` that carries delivery events. The stack for Shipped sends from `shipped.anth.us`; its identity, DKIM and MAIL FROM checks all pass.

The stack does not send mail and does not lift the SES sandbox. Parameters, the deploy command, verification checks and teardown are in `infra/newsletter/README.md`.

## The newsletter plugin: double opt-in

Status: Built (PPY-949d68), enabled on Shipped and Distinctive. This is the foundation: the subscriber store, signup and the confirmation email. It stands apart from the `signup` plugin above, which only stores an address.

### Enabling it

Prerequisites: the sending stack for the site is deployed (identity verified, configuration set `papyrus-<siteId>`), and the AWS account is still in the SES sandbox or has production access. In the sandbox SES delivers only to verified addresses, so a confirmation to an ordinary reader is refused until production access is granted. The signup form still answers "check your inbox" (it never reveals delivery), so check the function's logs for `confirmation_send_failed`.

```ts
backend: {
  plugins: [
    {
      name: "newsletter",
      siteId: "shipped",                                   // the sending stack's SiteId
      siteOrigin: "https://shipped.anth.us",               // the public origin; the plugin's links and redirects are built on it
      basePath: "",                                        // projection.json urls.basePath ("/posts" for dataparade.io/posts); omit for a site at the root
      computeRoleArn: "arn:aws:iam::<account>:role/<the CmsComputeRoleArn output>",
      sendingDomain: "shipped.anth.us",
      fromAddress: "newsletter@<sendingDomain>",              // a mailbox name at sendingDomain
      fromName: "Shipped",
      instantAlerts: false,                                // must be true before any alert list may use approval: "none"
      theme: { accent: "#...", text: "#...", background: "#...", fontFamily: "...", logoUrl: "https://..." }, // branding keys: see "Email theme fields"
      lists: [
        { id: "weekly", name: "...", description: "...", kind: "roundup",
          schedule: { draft: "cron(0 13 ? * FRI *)", timezone: "America/New_York" }, issueType: "newsletter_issue", archivePath: "/roundup/" },
        { id: "alerts-x", name: "...", description: "...", kind: "alert", rule: { sections: ["..."], tags: ["..."], types: ["..."] }, approval: "admin" },
      ],
      // configurationSet and eventTopicName default to papyrus-<siteId> and papyrus-newsletter-events-<siteId>.
    },
  ],
},
```

Invalid settings stop the synth with a readable message: unknown keys, a `fromAddress` off `sendingDomain`, duplicate or malformed list ids, a bad cron or time zone, a roundup without `archivePath`, and `approval: "none"` without `instantAlerts: true`. `schedule`, `issueType`, `archivePath`, `rule` and `approval` are validated now and used by the roundup and alert stories. An alert list with no `rule` matches every published item (an admin still approves each one).

Enabling it is a backend deploy that adds one stack, `newsletter`: a DynamoDB table (retained), a customer-managed KMS key (rotation on, retained), the SSM SecureString `/papyrus/<siteId>/newsletter-key` (generated once, never overwritten, retained) and the `newsletter` Lambda (Python 3.12, arm64, 512 MB, 30 s). It adds no GraphQL model or operation. It publishes `custom.papyrusPlugins.newsletter` (`contract`, `fromName`, `basePath`, list ids, names, descriptions and kinds, `theme`) and `custom.newsletter.actionsFunction` to `amplify_outputs.json`; the CMS routes read both. The IAM role of the function may use the table and its key, read its one parameter, and send mail from `fromAddress` through the site's identity and configuration set only. Only the CMS compute role may invoke it (a resource policy). The CMS app can also take the function name from `PAPYRUS_NEWSLETTER_FUNCTION`.

The plugin needs the CMS app's `/api/*` routes (`app/api/newsletter/*`). They ship with Papyrus, so `papyrus-app sync` adds them to a site repo. A site without the plugin answers 404 on both.

### Routes and form

- `POST /api/newsletter/subscribe`: JSON `{email, lists, page, website, renderedAt, consent, formId}` (8 KB cap, same-origin `Origin` required, or a same-origin `Referer` when there is no `Origin`; `lists` is an array or a comma string). Answers `202 {"status":"check_email"}` for any valid-looking request, `400 {"status":"invalid_email"}` or `{"status":"invalid_lists"}`. A signed-in reader's `siteSubject` is stored with the profile when present; it is never required or logged.
- `POST /api/newsletter/confirm` (form field `t`, same-origin form post from the confirm page) confirms and answers `303` to `<base>/newsletter/confirmed/?lists=<ids>&token=<manage token>`; any failure answers `303` to `<base>/newsletter/expired/`. `GET /api/newsletter/confirm?t=` exists only for confirmation emails sent before the pages moved: it changes nothing and answers `302` to `<base>/newsletter/confirm/?token=`.
- `GET /api/newsletter/state?kind=confirm&t=`, `?kind=preferences&t=` and `?kind=lists&lists=a,b`: JSON for the pages' script (see below). Read only; a bad token answers `400 {"status":"invalid"}`, a function failure `502`.
- Web component `/_plugins/papyrus-newsletter@1.js` (written to the site bucket when the plugin is on):

```html
<script src="/_plugins/papyrus-newsletter@1.js" defer></script>
<papyrus-newsletter lists="weekly,alerts-x"
  consent="I agree to get the weekly email and alerts, and can unsubscribe at any time."></papyrus-newsletter>
```

Attributes: `lists` (comma separated list ids), `data-lists` (JSON array of `{id,name,description}` taken from `custom.papyrusPlugins.newsletter.lists`, labels the checkboxes; or set `window.papyrusNewsletter = { lists }` once), `consent` (the sentence shown and stored as evidence), `endpoint` (default `/api/newsletter/subscribe`), `form-id`, `label`, `button`, `success`. One list: no checkbox. Several: unticked checkboxes, at least one required. No inline script or style attribute, so it works under a strict CSP.

### People get clean URLs; `/api` is for machines

Rule (Ryan, for Papyrus core and every site): people never land on, and are never sent to, an `/api/...` URL. `/api/*` is only for machine endpoints: form POST targets, the RFC 8058 List-Unsubscribe-Post and JSON. Everything a person opens or ends up on is a real page of the site, served by the static projection, with the site's chrome, theme, light and dark, header and footer.

| Human (static pages, `<base>` is the site's `urls.basePath`) | Machine (`/api/newsletter/*`, at the host root) |
| --- | --- |
| `<base>/newsletter/confirm/?token=<confirm token>`: the Confirm button in the confirmation email. Names the lists, then a form posts to the confirm endpoint. | `POST confirm` (form `t`): confirms, `303` to `confirmed` or `expired`. |
| `<base>/newsletter/confirmed/?lists=<ids>&token=<manage token>`: "You are subscribed", names the lists, links to preferences. | `GET confirm?t=`: legacy; `302` to the confirm page. |
| `<base>/newsletter/preferences/?token=<manage token>`: tick lists, save, unsubscribe from everything, delete my data. `&msg=saved`, `&msg=unsubscribed` and `&step=delete` (the confirm step) are states of the same page; `?msg=deleted` (no token) says the data is erased. The "manage" link in every email. | `POST preferences` (form `t`, `action=save\|unsubscribe_all\|delete`, `confirm=1`, `l`): `303` back to the preferences page, or `expired`. `GET preferences?t=`: legacy; `302` to the page. |
| `<base>/newsletter/unsubscribe/?token=<manage token>[&list=<id>]`: a button. The footer unsubscribe link in every email. | `POST unsubscribe` (form `t`, `l`, `page=1`): `303` to `unsubscribed`, or `expired`. `GET unsubscribe?t=&l=`: legacy; `302` to the page. |
| `<base>/newsletter/unsubscribed/?lists=<ids>&token=<manage token>`: the result, with a link to preferences to re-subscribe. | `POST unsubscribe?t=&l=` with `List-Unsubscribe=One-Click` (RFC 8058, from mail providers): `200 Unsubscribed.`, never a redirect. The only machine URL in an email, in the `List-Unsubscribe` header. |
| `<base>/newsletter/expired/`: an expired, used or invalid link, a cross-site post, or a function failure. One generic page. | `GET state?kind=confirm\|preferences&t=` and `?kind=lists&lists=`: JSON for the pages. |

The pages are always the directory form (`newsletter/confirm/index.html`), whatever `urls.style` says, because the emails link to those exact addresses. The edge serves them from the S3 projection like any other page; the CMS app is only behind `/api/*`.

- **Projection.** When `newsletter` is in `PAPYRUS_PLUGINS`, the standard projector writes the six pages (`src/papyrus_content/projection/standard/newsletter_pages.py`) through the normal page template, so they have the site's full chrome. They are `noindex` (meta and `robots`), carry `<meta name="referrer" content="same-origin">` so the form posts send the site's real `Origin`, and have no Markdown twin and no place in any sitemap, `llms.txt`, `llms-full.txt` or feed. The bodies use the standard front end's classes (`markus-document`, `markus-button` with `data-variant="secondary"`, `markus-actions`, and small baseline classes in `markus-components.css`), so a site's theme styles them with no newsletter-specific CSS. A full projection (`project --all`, the post-deploy render that `reprojectOnDeploy` runs, `project_listings`) writes them, and enabling the plugin on an existing site needs one. A site without the plugin has no such pages. A page left behind by an earlier version, `_plugins/newsletter-shell/index.html`, is owned by the reconcile and removed. A reconcile never deletes the six pages unless the verified deployed plugin list lacks `newsletter`; a CLI run reads the list from `amplify_outputs.json` (`custom.papyrusPlugins`) or `PAPYRUS_PLUGINS`, and refuses when it is unknown or differs.
- **Script.** `/_plugins/papyrus-newsletter-pages@1.js` (written with the other plugin assets, an external script, no inline script or style) reads `token`, `list`, `lists`, `msg` and `step` from the query string. It fills the hidden `t` (and `l`) fields of the forms, which post to the machine endpoints, and asks `/api/newsletter/state` for list names and, on the preferences page, the subscriber's state. A link that is no good sends the browser to the expired page with `location.replace`. Without JavaScript a page shows "This page needs JavaScript." and no form; nothing links to `/api`.
- **basePath.** A site under a base path (`dataparade.io/posts`) sets the plugin's `basePath` to its `urls.basePath` (`"/posts"` or `"posts"`; validated as lowercase path segments, at most three). The function builds email links with it (`SITE_BASE_PATH`), the CMS routes redirect to `<base>/newsletter/...` (it is in the public settings), and the projector writes the pages under it. The machine endpoints stay at `/api/newsletter/*` on the host root, like the signup component's. The two settings must be kept equal by hand, like `itemUrlStyle` and `urls.style`.
- **Headers.** The projected pages are ordinary static pages. The `/api` redirects send `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
- **Failures.** The edge turns an origin 403 or 404 into the site's 404 page, so the routes never rely on them for a person: a failed form post from a page is a `303` to the expired page, and only transport problems no browser form can cause (wrong content type, oversize body, an unknown action) answer JSON.

### Same-origin form posts and the edge

The subscribe, confirm and preferences posts must come from the site's own pages: `Origin` equals the public site origin (`PAPYRUS_SITE_ORIGIN`), or, when the browser sent no `Origin`, `Referer` is on that origin. `Origin: null` is never accepted (RFC 8058 unsubscribe, which has no origin check, is the one exception). A refused subscribe answers **400** JSON. A refused confirm or preferences post is a `303` to the expired page, so a person never sees an `/api` answer. Never 403 or 404: the CloudFront distribution replaces an origin 403 and 404 with the site's `/404.html` ("Page not found"), which hides the real answer. Use 400, 409, 410 or 422 for failures a reader can see.

The projected pages carry `<meta name="referrer" content="same-origin">`. They must not say `no-referrer`, because a browser then sends `Origin: null` on its form posts. That was the cause of "Confirm subscription" landing on the site's 404 page (found on Shipped).

### What subscribing does

The answer is `check_email` whatever the site knows about the address. A bot (filled `website` field, or a form submitted within 2 s or after 24 h) is accepted silently and nothing happens. Rate limits: 5 per visitor address per 10 minutes, 3 per subscriber per hour, 300 per site per hour; a limited request is still answered `check_email`, sends nothing and logs a CloudWatch EMF metric (`SubscribeRateLimited`, dimension `Scope`). A suppressed address gets nothing.

- New address: a `pending` profile with the consent evidence (`requestedAt`, `formId`, `pageUrl`, the exact wording the form showed, a keyed hash of the visitor address), `pending` list rows, a fresh nonce, and the confirmation email. Pending profiles expire after 30 days (DynamoDB TTL).
- Pending (or unsubscribed) address: a fresh nonce and list set replace the old ones, the earlier link stops working, and the confirmation is resent.
- Confirmed address asking for a new list: a confirmation for only the new lists. Nothing new: nothing happens.
- Confirming (the POST from the confirm page): the token must be valid, unexpired (72 hours) and carry the profile's current nonce, which is cleared at once, so a link works once. The profile becomes `confirmed` (with `confirmedAt`, the confirming IP and user agent), the list rows become `subscribed` with `gsiList` set, and the response includes a manage token for the later preferences story.

The confirmation email is built by `email_render.render_transactional` (theme from the plugin's `theme`), sent with SESv2 from `"<fromName>" <fromAddress>` with the configuration set and the tags `site` and `kind=confirm`.

### Data model

One DynamoDB table (not a GraphQL model; subscriber data never appears in the content API). Keys `pk`, `sk`; TTL `expiresAt`; GSI `byList` on `gsiList` + `sk` (keys only); on demand; customer-managed KMS key; point-in-time recovery off so erasure is real.

| pk | sk | Holds |
|---|---|---|
| `SUB#<hid>` | `PROFILE` | `email` (normalized), `status` pending / confirmed / unsubscribed, `createdAt`, `updatedAt`, `rev`, `siteSubject?`, `confirmNonce?`, `consent` {`requestedAt`, `formId`, `pageUrl`, `wording`, `requestIpHash`, `confirmedAt`, `confirmIp`, `confirmUserAgent`}, `history` [{`at`, `event`}] capped at 50 |
| `SUB#<hid>` | `LIST#<listId>` | `status` pending / subscribed / unsubscribed, `at`; `gsiList` = list id only while subscribed on a confirmed profile |
| `SUPP#<hid>` | `SUPP` | suppression (`reason`, `at`); checked before every send. Written by a later story. |
| `RATE#<kind>#<key>#<window>` | `RATE` | request counters with TTL |

`hid` = hex(HMAC-SHA256(hashKey, lowercased trimmed address))[:32]. A profile is replaced only if its `rev` is the one that was read, in one transaction with its list rows. `hashKey` and the token key are HKDF-SHA256 derived (salt `papyrus-newsletter`, info `hash` / `token`) from the SSM parameter, which the function reads once per container. Later stories add `ISSUE#`, `ALERT#`, `ROUNDUP#` and `STATE` rows to the same table.

### Tokens

`v1.<base64url(json)>.<base64url(hmac-sha256)>`, the HMAC over `v1.<base64url(json)>` with the token key, compared in constant time. The JSON holds `h` (hid), `p` purpose (`confirm` or `manage`), optionally `l` (list ids), `n` (nonce) and `e` (expiry, epoch seconds). Confirm tokens carry `n` and `e` (72 hours) and are single use. Manage tokens (for the unsubscribe and preferences stories) have no expiry and die with the subscriber record.

### Unsubscribe, preferences and erasure (PPY-b5a699)

Status: Built, live on Shipped and Distinctive.

- **Links.** `papyrus_content.newsletter.links` exports `make_manage_token(hid)`, `manage_urls(hid, list_id=None)` and `page_url(origin, base_path, page, query)` for the sender. `manage_urls` returns `{"manage_url": <origin><base>/newsletter/preferences/?token=<token>, "unsubscribe_url": <origin><base>/newsletter/unsubscribe/?token=<token>[&list=<listId>], "one_click_url": <origin>/api/newsletter/unsubscribe?t=<token>[&l=<listId>]}`. The first two are for people (email footers); `one_click_url` goes only in the `List-Unsubscribe` header. The confirmation email's button goes to `<origin><base>/newsletter/confirm/?token=<token>`. They read `KEY_PARAMETER`, `SITE_ORIGIN` and `SITE_BASE_PATH` from the environment (or take `keys=`, `site_origin=` and `base_path=`). No address ever travels in a link. Confirming a subscription returns a manage token, and the confirmed page links to the preferences page with it. The preview and test-send renders use `#preview` and `#test` placeholders, not links.
- **`POST /api/newsletter/unsubscribe?t=&l=`** accepts RFC 8058 one-click: a POST from a mail provider's servers with the body `List-Unsubscribe=One-Click`. It has no same-origin check, accepts any content type, answers `200` with `Unsubscribed.` and is idempotent (a repeat, or a token whose subscriber was erased, still answers 200; an invalid token is 400). A POST needs that marker or `page=1` from the unsubscribe page, which gets a `303` to the unsubscribed page. `GET` changes nothing and answers `302` to `<base>/newsletter/unsubscribe/?token=&list=`.
- **Preferences.** The page (state from `GET /api/newsletter/state?kind=preferences&t=`) lists every list with a tick for the ones the subscriber has, with the address masked (`r***@example.com`). The same-origin form `POST` to `/api/newsletter/preferences` has three buttons: save (the ticked set becomes the subscription), unsubscribe from everything, and delete my data, which first redirects to the page's confirm step (`&step=delete`). Ticking a list again re-subscribes with no new opt-in, because the manage token proves control of the inbox. If the address was suppressed for a bounce or complaint, a deliberate re-subscribe removes the `SUPP#` row and the address from the SES account suppression list (`DeleteSuppressedDestination`); a manual suppression is never lifted this way.
- **Function actions** (added to the dispatch table): `preferences_state`, `update_preferences`, `unsubscribe` (token, optional list; none means all), `delete_subscriber` (token), `admin_erase` (email, for the newsroom panel) and `resume_sending`. The last two do no authorization themselves: only the CMS compute role can invoke the function, and the public routes never send them. The newsroom story must check the admin group before calling them.
- **Erasure** removes `PROFILE`, every `LIST#` row, the `SUPP#` row and every send-ledger row of the subscriber. Ledger rows are found through the sparse GSI `byHid` (partition key `gsiHid`, keys only): the sender must write `gsiHid = <hid>` on every `ISSUE#<id>` / `SEND#<hid>` row (`records.LEDGER_HID_ATTRIBUTE`). That costs one attribute per row and no second write, where a profile list of issue ids would cost an update per send. Rate counters (2 hours) and the event log (90 days, below) expire by TTL.
- **Suppression.** `suppression.is_suppressed(hid)` is for the sender, as is `pause.is_paused()`. The confirmation email carries the `sub` tag too, so a permanent bounce of a confirmation also suppresses.

### SES events and the pause

The plugin stack subscribes the function to the sending stack's SNS topic (`papyrus-newsletter-events-<siteId>`, by literal name; the sending stack must exist first). Events map back to a subscriber with the message tags `sub` (subscriber id), `issue` and `list`; an event with no valid `sub`, from another site, or of another type (Send, Open, ...) is ignored.

| Event | Effect |
|---|---|
| Bounce, Permanent | `SUPP#` row (`bounce`), unsubscribe from every list, history entry; with an `issue` tag the ledger row becomes `bounced` and `counts.bounced` goes up |
| Bounce, other types | counted only (`counts.softBounced`); nothing else changes |
| Complaint | `SUPP#` row (`complaint`), unsubscribe from every list; ledger `complained`, `counts.complained` |
| Delivery | ledger `delivered`, `counts.delivered` (never overwrites a bounce or complaint) |
| Reject, Rendering Failure | ledger `failed`, `counts.failed` |

Ledger and counter updates are conditional and happen once per change, so duplicate notifications count once and a missing ledger row or issue is a no-op. Every handled event also writes a row `EVENTS` / `<iso>#<messageId>#<type>` with only the subscriber id, type, issue, list and bounce type, which expires after 90 days; the newsroom history will read these.

Two CloudWatch alarms (`papyrus-newsletter-<siteId>-bounce-rate`, `-complaint-rate`) evaluate `IF(sent >= 50, FILL(events, 0) / sent, 0)` over a 24 hour period on the metrics `Send` and `Bounce` or `Complaint` (namespace `AWS/SES`, dimension `ses:configuration-set` = the configuration set, written by the sending stack's CloudWatch destination). Thresholds are 4% bounces and 0.08% complaints; missing data does not alarm. They notify the SNS topic `papyrus-newsletter-alarms-<siteId>`, which invokes the function. On ALARM the function turns the configuration set's sending off (`PutConfigurationSetSendingOptions`, IAM limited to that set) and writes `STATE` / `SITE` `{paused: true, reason, pausedAt}`; `resume_sending` turns both back. The metric names follow the SES documentation for CloudWatch event destinations and were not checked against a live account.

### Live check with the mailbox simulator

`python -m papyrus_content.newsletter simulate --site-id <id> --from-address <address on the sending domain> --from-name <name> --outcome success|bounce|complaint --hid <32 hex subscriber id> [--issue <id>] [--list <id>]` sends one tagged test message through the site's configuration set to the matching Amazon SES mailbox simulator address, so no inbox is involved. `--dry-run` prints the request. Run it with credentials that may send from the identity, then look for the `EVENTS` row, the `SUPP#` row and the ledger update.

### Known gaps

The sender (PPY-3ae3b9) writes `gsiHid` on every ledger row, as above, so erasure finds them. Events carry the subscriber id, a pseudonym, so the 90 day event log is not erased with the subscriber; it expires. A form left open more than 24 hours is accepted silently and sends nothing; the reader has to reload and try again.



## Issues, approval and sending

Status: Built (PPY-3ae3b9). The newsroom Newsletter panel (below) drives these operations.

A roundup issue is an `Item` of the list's `issueType` (default `newsletter_issue`), so editors write it in the ordinary newsroom editor (open it at `/newsroom/articles/<itemId>`; the article list does not show other types yet). The newsletter table holds its send state in `ISSUE#` rows. When the send finishes, the Item is published through `content-actions` (`publishItem`), so the standard front end gives it a page, a Markdown twin and an `llms.txt` entry, and lists it on the archive page.

### Issue lifecycle

```mermaid
stateDiagram-v2
    [*] --> draft: schedule assembles the week, or a manual draft
    draft --> scheduled: admin approves for a time
    scheduled --> scheduled: admin approves again (new time)
    scheduled --> draft: admin cancels
    scheduled --> draft: start-send finds the item edited
    scheduled --> blocked: no postal address, or site paused
    blocked --> scheduled: cause fixed, admin approves again
    scheduled --> sending: start-send passes every check
    sending --> sent: every queued address is accounted for
    sending --> stopped: admin stops it, or the site is paused
    sent --> [*]: roundup Item published to the archive
```

`awaiting_approval` and `cancelled` belong to alerts (below). A `blocked` issue is fixed at its cause (configure the address, resume the site) and approved again.

### Archive: what a site puts in projection.json

The projector decides a page by section, and which Item types it projects by `listings.types`. A site archives its roundup with exactly this, where `roundup` is the last segment of the list's `archivePath` (`/roundup/`) and `newsletter_issue` is its `issueType`:

```json
{
  "urls": {
    "style": "directory",
    "sections": {
      "roundup": { "base": "roundup", "label": "Roundup", "description": "Every weekly issue.", "feed": false }
    }
  },
  "listings": { "types": ["article", "newsletter_issue"] }
}
```

Core change (PPY-3ae3b9): until now only `article` and `page` Items were projected whatever the settings; the projector now also projects every type in `listings.types` (`StandardMarkusProjector.projectable_types`, `PublishedContentSource.extra_types`). Sites that do not list a type project nothing for it, as before. `feed: false` keeps issues out of the site feed. The plugin setting `itemUrlStyle` (`html`, `directory` or `clean`, default `html`) must equal `urls.style`: roundup drafts link to published items with it. `archivePath` is one path segment because it is also the Item section and the `urls.sections` key.

Item `type` is a free string in the Item model and in `saveItemDraft`; the newsroom article editor's Type menu offers only `article` and `page` and its list loads only those types, so an issue is opened by id. Epic PPY-cf5e4c (publication-defined shapes) names "newsletter issue" as a shape; `newsletter_issue` is that string.

### Drafting the roundup

Each roundup list gets an EventBridge Scheduler schedule (`CfnSchedule`) from `schedule.draft` in `schedule.timezone`, which invokes `newsletter` with `{"task":"assemble-roundup","listId":...}`. The task:

- takes the published, non-issue Items published after the last sent issue of that list (else the last seven days);
- writes a draft Item titled `<list name>: <date range in the schedule's time zone>` in section `<archive segment>`, slug the local date, whose Markus body is an intro placeholder line followed by the items grouped by section (linked title, then the front matter description, summary, dek or standfirst);
- writes the `ISSUE#<issueId>` row (`draft`, kind `roundup`, `itemId`, subject = title);
- is idempotent per list and ISO week through `ROUNDUP#<listId>` / `PERIOD#<yyyy-ww>` (a conditional put; a claim whose issue row was never written is finished on retry);
- writes nothing when the window has no items (it logs `roundup_empty`).

No LLM is involved. Section headings are the Item section names, capitalised; links use `<siteOrigin>/<section>/<slug>` in the site's URL style.

### Operations (for the newsroom panel)

Eight Amplify custom operations (six more for the panel, below), all `input: AWSJSON` in and `AWSJSON` out. AppSync admits the groups below; the function checks the identity claims again. They enter through a thin function (`papyrus-newsletter-ops`) that forwards the verified claims and the input to `newsletter`. The recipient of a test send is the caller's own `email` claim, never the input.

| Operation | Kind | Groups | Input | Output |
|---|---|---|---|---|
| `newsletterIssues` | query | editor, admin | `{listId?, status?, limit?}` (limit 1 to 200, default 50) | `{ok, issues: [Issue]}` newest first |
| `newsletterIssue` | query | editor, admin | `{issueId}` | `{ok, issue: Issue + contentHash?, editedSinceApproval?}` |
| `newsletterPreview` | query | editor, admin | `{issueId}` | `{ok, subject, html, text, bytes, postalAddress, contentHash}` (footer links are `#preview`) |
| `newsletterApproveIssue` | mutation | admin | `{issueId, sendAt}` ISO 8601 | `{ok, issue, adjusted, warnings: []}` |
| `newsletterCancelIssue` | mutation | admin | `{issueId}` | `{ok, issue}` |
| `newsletterStopIssue` | mutation | admin | `{issueId}` | `{ok, issue}` |
| `newsletterTestSend` | mutation | editor, admin | `{issueId}` | `{ok}` |
| `newsletterCreateDraft` | mutation | editor, admin | `{listId}` (a roundup list) | `{ok, status: "created", issueId, itemId, items}` |

`Issue` is `{issueId, listId, listName, kind, itemId, subject, status, sendAt, approvedBy, approvedAt, sentAt, counts: {queued, sent, failed, suppressed, skipped, delivered, bounced, complained}, note, archiveUrl, createdAt, updatedAt}`; absent fields are omitted. `sendAt` is stored in UTC. A failure is `{ok: false, error, message}` with `error` one of `forbidden`, `not_found`, `invalid_state`, `item_missing`, `render_failed`, `bad_request`, `no_address`, `postal_address_missing`, `unavailable`.

Approval renders the Item's current Markus body (a body that does not render is refused), stores `contentHash` (sha256 of the subject, a blank line and the body) and creates the one-time schedule `papyrus-nl-<siteId>-<issue8>` at `sendAt` (UTC, `ActionAfterCompletion: DELETE`, flexible window off). A `sendAt` in the past or under two minutes ahead becomes now plus two minutes (`adjusted: true`). Approving again updates the same schedule. `warnings` says so when the postal address is not configured yet. Cancelling deletes the schedule and returns the issue to `draft`.

### Sending

`start-send` (fired by the schedule) re-validates, in this order, and does nothing else if any check fails:

1. The status is `scheduled`.
2. The content hash is unchanged. If not, the issue goes back to `draft` with the note "edited after approval; approve again" and nothing is sent.
3. The postal address resolves (below). If not: `blocked`, note "postal address missing".
4. The site is not paused. If it is: `blocked`, note "site paused".

Then it renders the issue once (the reason sentence, the postal address and a manage and an unsubscribe link placeholder), stores the HTML and text on `ISSUE#<id>` / `RENDER`, sets `sending` and `counts.queued`, and sends every subscriber id from the list's `byList` index to the SQS queue in messages of up to 50 (`{issueId, hids}`).

The worker (`papyrus-newsletter-send-<siteId>`, SQS batch size 1, reserved concurrency 1, timeout 180 s, queue visibility timeout six times that, three receives then the dead letter queue) handles a message like this:

- the issue is reloaded; if it is no longer `sending` (stopped, blocked) the message is dropped, and the site being paused stops the issue;
- for each subscriber id: `suppressed` if suppressed, `skipped` if the profile is not confirmed or the membership is not subscribed (both are written to the ledger and counted once);
- otherwise the ledger row `ISSUE#<id>` / `SEND#<hid>` is created with `attribute_not_exists` **before** SES is called. A failed condition means it was handled: a row still `claimed` (a worker died after claiming) is counted `failed` with error `interrupted` and never mailed;
- SESv2 `send_email` with Simple content, `List-Unsubscribe: <unsubscribe URL>` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, the configuration set and the tags `site`, `list`, `issue`, `sub` (= the subscriber id); a throttled call sleeps 1, 2 and 4 seconds and tries again; any other error is recorded as `failed` with its code;
- the row becomes `sent` (with the SES message id) or `failed`, and `counts` is incremented, in one transaction;
- calls are spaced to the account's `MaxSendRate` (from `sesv2 get_account`, cached five minutes, never below one a second);
- when too little time remains, the unprocessed ids go back to the queue as a new message;
- when `sent + failed + suppressed + skipped` reaches `queued` the issue becomes `sent` through a conditional update, so exactly one invocation completes it. A roundup is then published (the archive); if that fails the issue stays `sent` and its `note` says to publish the Item from the newsroom.

SES custom headers need a boto3 whose SESv2 model has `Simple.Headers`; the function bundles `boto3>=1.35.8` and a test fails if the installed one lacks it.

### Test send

`newsletterTestSend` mails one copy to the signed-in editor's own address: subject prefixed `[Test]`, the real footer with non-working `#test` links, no unsubscribe headers, no ledger row, and only the tags `site` and `kind=test`. It still needs the postal address.

### Postal address

Read at send time from SSM String parameters: `/papyrus/<siteId>/email/postal-address` first, else `/papyrus/email/postal-address`, cached five minutes. The functions may read exactly those two parameters. Neither, or a blank value, blocks issue sends and approval says so in `warnings`. The value is never stored in the repository, logged or put in a test. Tests use a placeholder.

### Operator notes

- Environment (all set by the plugin): `FUNCTION_ARN`, `SCHEDULER_ROLE_ARN`, `QUEUE_URL`, `CONTENT_ACTIONS_FUNCTION`, `PAPYRUS_GRAPHQL_ENDPOINT`, `ITEM_URL_STYLE`, plus those of the double opt-in. `LISTS_JSON` also carries a roundup's `issueType`, `archivePath` and `timezone`.
- IAM: `newsletter` may create, update and delete schedules named `papyrus-nl-<siteId>-*`, pass the one scheduler role, send to the queue, read the two postal parameters, invoke `content-actions`, and call five AppSync fields (`Query.getItem`, `Query.getPublishedItem`, `Query.listPublishedItems`, `Mutation.createItem`, `Mutation.updateItem`). The worker may read and write the table, receive from and send to the queue, invoke `content-actions`, read the key parameter, send through the site identity and configuration set, and call `sesv2:GetAccount` (no resource-level form exists). The AppSync function may only invoke `newsletter`.
- To stop a send in progress, an admin calls `newsletterStopIssue`: workers drop the remaining messages and the counts stay as they were.
- A message in the dead letter queue (`papyrus-newsletter-send-<siteId>-dlq`) is a batch that failed three times (a missing render, SES unreachable). The ledger makes it safe to redrive: addresses already handled are skipped.
- A `blocked` issue needs its cause fixed (create the postal address parameter, resume the site) and an admin to approve it again; approval accepts `blocked`.

### Known gaps

- Reserved concurrency 1 on an SQS-fed function can make Lambda poll while the function is busy; those throttled receives count toward the three before the dead letter queue. Watch the dead letter queue on the first large send; a larger `maxReceiveCount` or chaining messages (each message enqueues the next) removes the risk.
- The window is read by scanning the published item summaries (as the projector does); a very large site may want an index by publish time.
- Link paths assume a section's `base` equals its name. A section declared with another `base` would be linked wrongly in a draft (the editor fixes the link).
- The article list in the newsroom does not show issue types; the panel links to the editor by item id.
- `compliance.py` binds the unsubscribe story's `links`, `suppression` and `pause` calls to the sender's store and keys.

## Alerts: publish-triggered (PPY-d415c0)

Status: Built. An alert list sends one short email when a matching item is published. Alerts hang off the Papyrus publish event and nothing else: not procedure runs, not monitor triggers.

### Configuration

```ts
newsletter: {
  // ...as above
  instantAlerts: false,            // true lets a list with approval: "none" send without an admin
  lists: [
    // Every published item, approved by an admin.
    { id: "all-alerts", name: "All alerts", description: "...", kind: "alert", approval: "admin" },
    // Items in either section, with a matching tag, of one type; OR within a field, AND across the fields present.
    {
      id: "rulings", name: "Rulings", description: "...", kind: "alert", approval: "none",
      rule: { sections: ["rulings", "notes"], tags: ["breaking"], types: ["article"] },
    },
  ],
}
```

`rule` is optional; absent or empty it matches every published item. Names compare without regard to case. A section is the item's section, a tag comes from the `tags` front matter, and a type is the item type. Items of any roundup list's `issueType` never raise an alert.

### How a publish reaches the newsletter

```mermaid
flowchart LR
    N[newsroom publishItem] --> C
    L[papyrus content publish] -->|projection task, marked published| C[content-actions]
    C -->|after a real publish, page live| H[announce_published]
    H -->|async Event| F["newsletter: item-published"]
    F --> D{ALERT# dedupe row}
    D -->|new| I[alert issue]
    D -->|exists| X[nothing]
    I -->|approval none and instantAlerts| S[start-send]
    I -->|otherwise| W[awaiting_approval]
```

`src/papyrus_content/publish_alerts.py` (`announce_published`) is the only code that invokes the newsletter function, from `content-actions`. It fires only for a real publish (`PublishResult.changed`), never for unpublish, edits that keep the same published content, or reprojection (`all`, `item-pages`, `deploy-render`):

- Newsroom: `publish_item_action` passes the published item id to `project_item_action` when `changed`. The announcement goes out once the page is live. If the projection failed, the scheduled retry carries the same marker and announces when it succeeds.
- CLI: `papyrus content publish` marks its projection task with the published item id when `changed`; `run_projection_task` announces after the projection succeeds. A task without the marker (a plain reprojection, `--no-trigger`, an unchanged republish) announces nothing.
- No `PAPYRUS_NEWSLETTER_FUNCTION` (the plugin is off): a no-op. Any error is logged and swallowed, with 2 and 3 second timeouts, so an alert problem never fails or slows a publish.

The plugin sets `PAPYRUS_NEWSLETTER_FUNCTION` on `content-actions` and grants it `lambda:InvokeFunction` on `papyrus-newsletter-<siteId>` only.

### What the function does

For each alert list whose rule matches, `alerts.py` takes a conditional-put dedupe row `ALERT#<listId>` / `ITEM#<lineageId>` (kept, never expired) and, if it was new, writes an issue of kind `alert` with `sourceItemId` and `lineageId`. A repeated event, a republish or an edit therefore never alerts again; a crash between the dedupe row and the issue is finished by the retry. No Item is created and there is no archive. The subject is the item title; the Markus body, stored on the issue row, is the title as a link, the dek (`deck`, or a `description`/`summary` style front matter field), the item's first paragraph of plain prose if it has one, and a "Read it on <site>" link. Links use `ITEM_URL_STYLE` as roundup drafts do. The footer says "You get this because you subscribed to <list name> on <site>."

An alert starts `awaiting_approval`; the admin approves it (`newsletterApproveIssue`), which schedules it like a roundup. Cancelling an alert (waiting or scheduled) ends it as `cancelled`; it does not return to draft. If the list has `approval: "none"` and the site has `instantAlerts: true`, the function approves it as `system:instant-alert` and calls `start-send` at once, so the content-hash, postal address and paused-site guards still run (a failure leaves it `blocked` for an admin). When an alert finishes `sent`, nothing is published.

### Known gaps

- Only `publishItem` (the newsroom action and the CLI) alerts. `saveItemDraft` on an already-live item, `papyrus story` commands and imports publish without an alert, on purpose: a bulk import must not alert.
- A CLI publish with `--no-trigger`, or on a site with no projection and no `content-actions` function configured, does not alert.
- A site that publishes an item before the matching alert list exists gets no alert for it (the event has passed).
- The alert shows no admin notification; the panel shows pending alerts.

## The newsroom Newsletter panel

Status: Built (PPY-4005de). Administration, Newsletter appears only when `custom.papyrusPlugins.newsletter` is in `amplify_outputs.json`; `?demo=1` shows it with fixture data (`lib/newsletter-fixture.ts`). Editors and admins open it; every operation is checked in AppSync and again in the function from the verified groups. It has no realtime subscription: it reloads after each action and on the Refresh button.

| Section | Who | What |
|---|---|---|
| Lists | editor, admin | confirmed, pending and unsubscribed per list, site totals (people, not memberships), and the suppressed count |
| Site status | editor sees, admin acts | a paused banner with the reason; admin **Resume sending** |
| Issues | editor, admin | filter by status; subject, list, status (word and mark), send time in the roundup list's time zone (UTC on hover), counts, the `note`, a blocked reason, and "edited since approval" for a scheduled issue. Links open the issue Item at `/newsroom/articles/<itemId>` and the archive page. **New draft** per roundup list. Unknown statuses (an alert kind may add its own) show as written; `awaiting_approval` is approved like a draft |
| Issue actions | | Preview (HTML in an iframe with `srcdoc` and `sandbox=""`, plain text in a `<pre>`), Test send (to your own address), and, admin only, **Approve for a time** (a `datetime-local` in the site zone, default the next whole hour), Cancel (scheduled), Stop (sending, with a confirm step). A missing postal address says an operator sets it in the site's AWS configuration |
| Delivery history | editor (masked), admin (full) | the ledger rows of one issue (result, queued and last event times, error code), paged, plus the recent events for that issue |
| Subscribers | admin | a paged table with list and status filters, **Export CSV** (confirmed and pending, with consent evidence, formulas neutralised by `lib/signup-csv.ts`), and erase by address with a confirm step |

### Operations added for the panel

All take AWSJSON `input` and return AWSJSON through `papyrus-newsletter-ops`, like the issue operations. Failures are `{ok:false, error, message}`.

| Operation | Kind | Groups | Input | Output |
|---|---|---|---|---|
| `newsletterOverview` | query | editor, admin | `{}` | `{ok, lists:[{id,name,kind,confirmed,pending,unsubscribed,timezone?}], totals, suppressed, paused, events}`; `events` are the last 100 (`type`, `at`, `issue?`, `list?`, `detail?`), never an address or subscriber id |
| `newsletterIssueDeliveries` | query | editor, admin | `{issueId, cursor?}` | `{ok, deliveries:[{address,status,at,eventAt?,error?}], cursor?}`; 100 a page; `r***@example.com` for editors, the address for admins, `(erased)` when the subscriber is gone |
| `newsletterSubscribers` | query | admin | `{listId?, status?, cursor?}` | `{ok, subscribers:[{email,status,lists,createdAt,confirmedAt?}], cursor?}` |
| `newsletterExport` | query | admin | `{cursor?}` | `{ok, rows, cursor?}`, 200 rows a page; the browser pages through and builds the CSV. No IP hashes, IPs or user agents |
| `newsletterErase` | mutation | admin | `{email}` | `{ok, removed}` |
| `newsletterResume` | mutation | admin | `{}` | `{ok, paused:false}` |

The Python actions are `panel_overview`, `panel_deliveries`, `panel_subscribers`, `panel_export`, `panel_erase` and `panel_resume` (`panel.py`); the internal `admin_erase` and `resume_sending` remain unauthenticated and are not reachable from AppSync.

### Counters

Counts are not scanned per request. Rows `COUNT#<listId>` / `COUNT` hold `confirmed`, `pending` and `unsubscribed` memberships; `COUNT#SITE` / `COUNT` holds the same three for profiles, `suppressed`, and `seeded` once a recount has run. `Store.save` adds the deltas in the same transaction as the membership rows (so signup, confirmation, list changes, unsubscribe, preference saves and the suppression-driven unsubscribe are all covered), and `records.put_suppression`, `delete_suppression` and `erase_subscriber` adjust the suppressed and membership counts next to their own writes. A test checks every transition against `recount`.

`recount` (an operator action: invoke the function with `{"action":"recount"}`; no AppSync operation) scans and rewrites every counter. The overview runs it by itself when `COUNT#SITE` is not `seeded`, so a site that had subscribers before this shipped is counted at first use. DynamoDB TTL deleting an expired pending row does not pass through code, so pending counts drift upward until the next recount.

### Known gaps

- The subscriber list and export scan the table (ledger rows included), a bounded window at a time. Fine to tens of thousands of subscribers; an index of profiles is the follow-up.
- Pending counts include rows past their 30 days until a recount.
- "Edited since approval" is read per scheduled issue (up to ten) after the list loads.
- The site time zone is the first roundup list's; a site with no roundup list uses the browser's zone.
