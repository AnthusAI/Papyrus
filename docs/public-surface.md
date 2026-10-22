# The public surface of a Papyrus site

What an anonymous visitor to a static Markus site can reach, what the projector
publishes for client-side use, and what must never be public. Pinned by
`procedures/newsroom/tests/test_guest_surface.py`.

## 1. Generated JSON next to the pages (use this first)

A site that opts in gets small static files, written by the projector at
publish time like any other generated page:

| File | Content |
|---|---|
| `/_data/search-index.json` | Every listed page, newest first: `{title, url, summary, tags, date}`, plus `image` and `publication` when known (below). |
| `/_data/latest.json` | The first `latestCount` entries of the same list (default 20). |
| `/_plugins/papyrus-search@1.js` | The `<papyrus-search>` component (section 2). |

They need no credentials, cost nothing per request, and cannot be abused. They
carry only front matter fields (`title`, `description`/`summary`/`excerpt`,
`tags`, `date`) and the page address: what the page HTML already shows. An item
with `feed: false` is left out.

**`image` and `publication`** (optional keys on every entry of both files, for
sites that syndicate each other's articles as cards):

- `image` is the entry's **absolute** Open Graph image URL: the front matter
  image (`image`, `cover`, `ogImage`, `thumbnail`) or else `seo.defaultImage`,
  made absolute with the site's origin by the same function the page's
  `og:image` tag uses (`HeadBuilder.og_image`). An image that is already an
  `http(s)` URL is kept as written. The key is **omitted**, never `null`, when
  the entry has no image or the site has no URL (no `productionUrl` and no
  `PAPYRUS_SITE_PUBLIC_URL`). An image the page takes only from its body (the
  first picture in the text) is not read, because that needs the rendered
  page: set `image` in the front matter to have it syndicated.
- `publication` is the site's name as the feeds title it (`feeds.title`, which
  defaults to `site.name`). It is omitted only when empty.
- The bare Markus projector (a `projection.json` with no `site` object) has no
  identity and no URL, so it writes neither key.

Existing keys, their order and their values are unchanged, and
`<papyrus-search>` reads only `title`, `url` and `summary`, so it ignores the
new keys. Readers should treat the file as open-ended and ignore keys they do
not know.

**Opt in** in the site's `projection.json`:

```json
{ "publicData": { "searchIndex": true, "latest": true, "latestCount": 20, "summaryCharacters": 240 } }
```

Omit `publicData` and nothing changes: no file is written and no template
differs. A site with its own projector calls `public_data_files`,
`public_data_inputs` and `public_static_files` from
`papyrus_content.projection.public_data` with its own entries.

**Incremental rule.** The files are listing-class pages: they depend on the
list of pages. The engine compares a digest of each file's bytes before and
after an edit, so an edit that does not change a title, summary, tag, date or
address (a body edit, say) writes neither file. Adding, removing, hiding,
retitling or re-dating a page writes the search index, and `latest.json` only
when the change reaches its first entries. A reconcile repairs both.

**Caching.** Same policy as HTML: `public, max-age=0, s-maxage=300,
stale-while-revalidate=60`, with the written paths invalidated in CloudFront on
every projection. A reader sees an edit within the freshness bound of the site's
edge settings (usually seconds). The CloudFront distribution should compress
`application/json`.

## 2. The `<papyrus-search>` component

One file, no framework, no build step. It loads the index on first focus,
filters in the browser (every word must match; title beats tag beats summary;
newest first among equals; accents ignored) and renders links into its own
light DOM, so the site's CSS styles it.

```html
<script src="/_plugins/papyrus-search@1.js" defer></script>
<papyrus-search></papyrus-search>
```

Attributes: `src` (default `/_data/search-index.json`), `placeholder`, `label`,
`limit` (10), `min-length` (2). Classes to style: `form.papyrus-search`,
`input.papyrus-search-input`, `p.papyrus-search-status`,
`ul.papyrus-search-results`, `span.papyrus-search-summary`. Without JavaScript
the element is empty and the page is complete for crawlers. Only same-site
addresses (starting with a single `/`) are linked.

**Using it from Markus pages.** Markus has no `:::search` directive, and
Papyrus cannot add one: directive names are validated by the pinned Markus CLI
and authors cannot write raw HTML. Put the element where the site owns the
HTML: a generated page's fragment (for example a `/search/` page), or the site
chrome (`SiteChrome.render_masthead`) together with
`SiteChrome.scripts = ("/_plugins/papyrus-search@1.js",)`. A content directive
would be a Papyrus sentinel construct (like `::image`); that is a decision for
when a second widget needs it, not part of this change.

## 3. What a guest can read through GraphQL and storage

Browser reads are possible but need Cognito JS, SigV4 signing and a cross-origin
call; use them only for what static JSON cannot do.

**Identity.** Guests are the Cognito identity pool's unauthenticated identity:
temporary credentials, SigV4-signed requests to AppSync (IAM authorization).
`export-published --auth guest` is the only command that uses this lane.
The API key mode (365 days) is enabled but no rule uses
`allow.publicApiKey`, so the key grants nothing.

**Models** (`allow.guest().to(["read"])`, nothing else), all
`modelWithoutSubscriptions`:

| Model | Fields a guest sees |
|---|---|
| `PublishedItem` | `id sourceItemId itemLineageId versionNumber type status typeStatus slug shortSlug section sectionStatus title headline deck body bodyMarkus bodyIr aliases metadata byline dateline publishedAt editionDate sortTitle pullQuotes layout editorial`. Indexes: `publishedItemBySlug`, `...ByTypeStatusAndPublishedAt`, `...BySectionStatusAndPublishedAt`, `...ByLineageAndVersion`. |
| `PublishedMediaAsset` | `id sourceMediaAssetId publishedItemId sourceItemId itemLineageId type role sortKey storagePath externalUrl alt caption credit width height aspectRatio focalX focalY minHeight preferredHeight maxHeight crop wrapsText metadata` |
| `PublishedEdition` | `id sourceEditionId editionLineageId versionNumber slug title status editionDate publishedAt description layoutPlan metadata` |
| `PublishedEditionItem` | `id publishedEditionId publishedItemId source*Id *LineageId placementKey sortKey pageNumber priority metadata` |
| `PublishedCategorySet` | `id sourceCategorySetId categorySetLineageId versionNumber corpusId classifierId displayName description status generatedAt publishedAt categoryCount metadata` |
| `PublishedCategory` | `id sourceCategoryId publishedCategorySetId categoryLineageId categorySetLineageId versionNumber corpusId categoryKey parentCategoryId parentCategoryKey displayName shortTitle subtitle description aliases status seedItemIds holdoutItemIds rank depth isPinned metadata` |

**Storage.** Guests read `media/*` only. `corpora/*`, `preview/*` and
`newsroom/*` are editor and admin only.

**Review of the guest-readable item (PPY-f293ea).** A CMS publish fills
`PublishedItem.metadata` with `frontMatterYaml` (the item's whole front matter),
`source.path`, `sourceContentHash` and `projection`; `layout` is
`{"source":"cms"}` and `editorial` is `{}`. Consequences:

- Everything in an item's front matter is public through GraphQL, not only the
  keys the page shows. Do not keep editorial notes, internal flags or contact
  details in front matter.
- `metadata` is copied from the draft `Item.metadata` as is. The only keys the
  code writes into it today are those above; a test fails if a publish adds
  another. Never write editorial notes into `Item.metadata`.
- Draft `Item`s are never public; only what `publishItem` copies is.

## 4. CORS and hostnames

The sites live on their own domains (`anth.us`, `pilobol.us`); the API is on
`<id>.appsync-api.<region>.amazonaws.com`. AppSync answers CORS preflight itself
for any origin, so there is no allow-list to configure and CORS is not an
access control. Abuse control for anything writable is authorization plus AWS
WAF. A custom API domain (`api.<site>`) is optional and later. The JSON files in
section 1 are same-origin and need none of this.

## 5. Must never be public

Drafts (`Item`), assignments, messages and threads, references, corpora,
`preview/*`, user profiles and roles, signup or comment entries (the `SignupEntry` model of the signup plugin has no guest rule), and any field
that carries editorial notes. No model other than the six above gets
`allow.guest`, `allow.publicApiKey` or `allow.custom`.

## 6. Guest writes: one narrow operation per plugin

The base surface has no guest write. A plugin may add one narrow custom mutation
(`submitSignup` is the first and only one): a Lambda handler validates and
length-limits its input, drops honeypot and too-fast submissions, throttles the
caller by address and identity, writes to a model nobody can read as a guest, and
sits behind an AWS WAF rate-based rule. A site gets it only by listing the plugin;
see [`docs/plugins.md`](plugins.md). Subscriptions, browser GraphQL reads for pages,
comments and a custom API domain are still out of scope.
