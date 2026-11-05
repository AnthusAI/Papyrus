# Share a Story by URL

An editor can show a Story in progress, in the website's real public layout and labelled DRAFT, to people who have no newsroom sign-in. Open it with the **Share a draft** icon (Lucide `Share2`) on the Story, or with `papyrus stories share`. This is a general Papyrus feature for every site that builds its public pages with the standard front end. Status: built, not yet deployed to any site.

It is not the newsroom preview (that needs a sign-in and shows the editor), and it is not staging (whole site, editor and admin only, banner says STAGING). Giving a stakeholder editor access to show them a draft would also give them write access; a link does not.

## What the person chooses

| Choice | Options | Default |
| --- | --- | --- |
| Who can open it | **Anyone with the link**: anyone who has the link can read the draft, with no sign-in. **Only people signed in to the newsroom**: signed in as an editor or admin, checked on the server; anyone else is sent to sign in, and a signed-in reader without the editor rights is told the link is not available. | Anyone |
| What it shows | **The current version**, which follows new versions as they are saved. **One version only**, which stays put. | Current |
| How long it lasts | 7, 30 or 90 days. There is no link that never expires. | 30 |

Publishing the Story ends its links: the old address shows a plain page that links to the published address (to a signed-in-only link, only after its sign-in rule is met). Spiking the Story ends its links too. A link made after publishing, for a later draft of a live Story, is fine; a link to the published version itself is refused, because that page is public. The editor can end any link from the dialog, which lists who made each link, who can view, what it shows, when it expires and when it was last opened. The list never shows a token again.

## How it works

- **Host.** The link lives on the console's own origin, at `/api/share/<token>`. The public site is static (S3 and CloudFront), so it has no server, no session and no place to check a token. The console's Next app already has the Cognito session a signed-in link needs and the backend's guest access, and it needs no edge, DNS or CloudFront change on any site. `/api` is exempt from the staging gate and from the newsroom-at-root rewrite, so the route works on every deployment shape. The cost: the address is the console's, not the public domain's, and the stylesheets, scripts and links of the page are the public site's (the page is rewritten to name the site's public origin).
- **Rendering.** The `viewStoryShare` query goes to the content-actions function, which runs the site's real projector (`item_pages`) on the chosen version of the Story and the published site index, into the response. It has no page writer, so nothing is written to the live site's prefix or bucket, and the result is not cached anywhere shared. `story_share_render.shape_share_page` then makes it a draft for every site at once (see below).
- **Token.** 256 bits from `secrets.token_urlsafe(32)` (43 URL-safe characters). Only the SHA-256 hash is stored, as the `StoryShare` record's id, so a view is one keyed lookup, and the hash is compared in constant time. The token is returned once, in the response that makes the link, and is never stored or logged (the function logs only an error's class). Anything that is not exactly 43 URL-safe characters is refused before any lookup.
- **One answer for every dead link.** Unknown, malformed, expired, revoked, ended by a spike, or a version that is gone: the same `{"state": "unavailable"}` from the function and the same "This link is not available" page, status 404, from the route.
- **Pictures.** The page's pictures are rewritten to `/api/share/<token>/media?u=<address>`. The function answers only for an address the link's own page asked for (exactly as written, of the version the link shows). A rendition on the public site is fetched from there; an original uploaded with the version is found among that version's `MediaAsset` rows and signed for a guest read of `media/*`. Only `image/*` is streamed, with `nosniff` and `Content-Security-Policy: default-src 'none'; sandbox`, so an SVG opened by itself cannot run script. Another Story's picture, a parent path, an encoded path, another host or a storage key is the plain "not available". Reaching another Story is impossible by construction: the token names one Story lineage and the allowed set is read from that page.
- **Headers on every response:** `X-Robots-Tag: noindex, nofollow`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`. The page also has a `noindex` meta and `referrer` meta, no canonical, `og:` or `twitter:` tags, no JSON-LD, no alternate or sitemap links, no Markdown page actions, and no analytics or consent scripts (the projector copy has its analytics id and consent mode removed; the shell strips any that remain).
- **The DRAFT band.** One band for every site, injected into the rendered page: the site's own `--papyrus-ink` and `--papyrus-bg` tokens swapped (system colours if a site has none), a flat fill with no outline, an inline Lucide `file-pen` icon and the word DRAFT, then what it is ("Not published. Shared by link, for review. Version 3 (follows new versions)."). The title is `DRAFT: <title>`. It is a sticky bar, so it is on screen however far the reader scrolls.
- **No listing.** A link is a record and a route. Nothing reads it to build a home page, section, feed, sitemap, `llms` file or snapshot, and a test checks that the site's output never mentions a shared draft.
- **What the page cannot show.** The page is drawn from the version's text and the published site; it never reads Messages, review requests, editorial notes, votes or stars, and a test asserts that none are read.
- **Signed in.** A visitor with a newsroom session asks the function as themselves (the Next route reads the session from the cookies); everyone else asks as a guest. The function reads the groups from the identity AppSync passed it, never from anything the browser sent. A signed-in link asked by a guest answers `sign-in`; the route redirects to `/newsroom/share/<token>`, which signs in and goes back to the link. A wrong token never answers `sign-in`, which would tell a stranger a link exists.
- **Creating, listing and revoking** need `editor` or `admin`, checked in the function as well as by the schema's groups.
- **Recorded on the Story.** The current version's metadata has `shareEvents`: `created` (who, who can view, what it shows, when it expires), `opened` (the day, once per link per day, nothing about the viewer: no address, agent or identity), `revoked` and `ended` (published or spiked). The link itself counts opens and keeps the day of the last one. The list is kept to the last 200 events, which keeps the Story's record far inside DynamoDB's 400 KB limit.

## The CLI

```bash
papyrus stories share --story <lineage> [--version N] [--signed-in] [--expires 7|30|90] [--dry-run] [--json]
papyrus stories shares --story <lineage> [--json]
papyrus stories share-revoke --story <lineage> --share <share id> [--dry-run] [--json]
```

They write by default; `--dry-run` previews and asks nothing. They ask the newsroom as the signed-in person (`papyrus login <site>`); there is no local fallback, because the page is drawn by the site's function. `share` prints the URL once, with a reminder that it cannot be shown again; `shares` lists the links without any URL.

## What a site needs to deploy

- A release of Papyrus with this feature, and a deploy of the site's backend: the new `StoryShare` model (one new table, with its one index created with it, so no existing table gets a new index), five new operations on the data API, and the content-actions function. Sites that left out optional model groups can leave out `shares`; sharing then answers that it is not available.
- The console app (the Next route `/api/share/[token]`, `/api/share/[token]/media`, and the sign-in page `/newsroom/share/[token]`), which `papyrus-app sync` copies in with the next release.
- The content-actions function needs `PAPYRUS_SITE_PUBLIC_URL` (or `site.productionUrl`), which every s3-projection site already sets: the page names the site's public origin for its stylesheets and pictures. Without it a link is refused when it is made, with the reason.
- No IAM, DNS, CloudFront or Cognito change. The console's Cognito identity pool already allows guests to call the data API and to read `media/*`.

## Where it does not work

- **Sites that do not build their public pages with the standard projector** (the `s3-projection` publication kind): sharing answers "not available on this site" when a link is made, and the Share icon shows that message. This includes Next-rendered (Pretext) publications, which render drafts on their own staging branch instead.
- **Stories whose type has no public page** (no `urls.types` entry and no section route) are refused when the link is made, with the reason.
- **A Story that has never been saved** has no lineage to share; the icon appears once it is saved.
- A site whose own page code reads anything private into a page (a custom `item_decorator` or an include that lists unpublished things) shows what that code adds. The share page adds nothing of its own.
- The page and its stylesheets are two origins (console and public site). A site whose public origin blocks cross-origin stylesheets or fonts would show an unstyled draft; none of ours does.
- AppSync carries the page in one response. A draft page over several megabytes would fail and answer "not available"; pictures are streamed separately and are not affected.

- The token is in the URL, so the browser's history, the CDN and the web server's access logs, and AppSync's request logs if someone turns on field-level logging, can hold it. Nothing in Papyrus writes it anywhere, and the `Referrer-Policy` keeps it from leaving in a Referer header. Treat "anyone with the link" as exactly that.
- An open count and the "last opened" day are approximate: two opens at the same moment can count once.

## Specs and tests

`features_backend/story-share-links.feature`, `features/story-share-links.feature`, and the unit tests `procedures/newsroom/tests/test_story_shares.py`, `test_content_actions_story_share.py`, `test_story_share_commands.py` and `scripts/test-story-share.ts`. They include the attack cases: wrong, malformed and path-trick tokens, expired and revoked links, another Story's pictures, a pinned version, a signed-in link with no sign-in, and a non-editor. `npm run test:story-share` runs them.

## For p.apyr.us

A docs task for the product site: a page under the newsroom docs called "Share a draft" with the choices above in the same words, the DRAFT label, the expiry options, "what anyone with the link means", the CLI, and a note that publishing or spiking ends links. It follows the rule that every Papyrus feature epic ends with a p.apyr.us docs task.
