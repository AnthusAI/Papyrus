# Building a Papyrus static site

A Markus static site is a `web/` folder and nothing else. Papyrus core renders it: pages, listings, tags, sitemap,
robots.txt, a 404 page, RSS and Atom feeds, and every head tag search engines and social cards read. A site
supplies **settings** (`projection.json`), a **theme** (CSS and tokens), **brand assets**, **nav and redirect data**
and, only when settings are not enough, a few **named hooks**. It does not write a projector, a sitemap writer, a
feed generator or an edge function.

Editorial content and anything that should change over time (articles, aliases, descriptions, dates, tags) is
backend data in the CMS, not a file in the repository.

## The smallest site

```json
{ "site": { "name": "Example" } }
```

Put that in `web/projection.json` and the site works: a home page, one page per published item at `/<slug>.html`,
one flat paginated listing at `/archive/`, tag pages when items have tags, `sitemap.xml`, `robots.txt`, `404.html`,
`feed.xml` and `atom.xml`. There are **no sections**: no section bases in URLs, no empty section pages, no section
UI. Sections are an option you add (below), never a requirement.

The top-level `site` object is the opt-in. A project whose `projection.json` has none keeps today's bare
`MarkusSiteProjector`, byte for byte.

## `projection.json`

Every block is optional except `site.name`. Unknown keys are errors.

| Key | Contents |
|---|---|
| `site` | `name`, `shortName`, `publisher`, `tagline`, `description`, `language` (default `en`), `productionUrl`, `author`, `componentsCss` (default `true`: ship the baseline component CSS), `summaryFields` (ordered front matter fields for the summary; default `description`, `summary`, `excerpt`, `blurb`, `dek`, `standfirst`) |
| `urls` | `style`: `html` (`/x.html`, default) or `directory` (`/x/`). `sections`: `{ "<section>": { base, label, description, pages, listing, feed, sitemap, linkField, pageSize, listEmpty } }`. Leave it out for a site without sections |
| `nav` | `links: [{label, href, cta}]`, `disclosure` (a menu button for narrow screens), `homeLabel` |
| `footer` | `columns: [{title, links}]`, `text` |
| `seo` | `defaultImage`, `imageSize: [w, h]`, `twitterSite`, `twitterCreator`, `jsonLdTypes: {section-or-type: "NewsArticle"}`, `defaultJsonLd`, `publisherName`, `breadcrumbs` |
| `sitemap` | `style`: `single` (`/sitemap.xml`) or `index` (`/sitemap-index.xml` + `/sitemap-0.xml`); `lastmod`; `tags` |
| `robots` | `extra`: extra lines |
| `feeds` | `formats` (`rss`, `atom`), `count` (30), `rssPath`, `atomPath`, `title` |
| `listings` | `pageSize` (10), `featuredCount`, `path` (the flat listing base, `archive`), `homeCount`, `tags`, `tagBase`, `types` (entry types that are listed, `["article"]`) |
| `fonts` | `stylesheet` (a font CSS URL; adds the `preconnect` links), `preconnect` |
| `icons` | `icon`, `iconType`, `appleTouch`, `manifest`, `themeColor`, `themeColorDark` |
| `environment` | `guard` (default `true`) |
| `redirects` | `exact: {"/old/": "/new/"}`, `patterns: [{pattern, to, status, except}]` |
| `pages` | custom generated pages: `[{id, path, title, description, dependsOn, sitemap, noindex}]`; the body comes from the `page_body` hook |
| `showcase` | a logo wall fed from published items: `{section, path, title, description, kinds}` (see "Showcase") |
| `components` | `itemByline`, `breadcrumbs`, `itemPagesDependOn` |
| `hooks` | path of the hooks module, relative to `web/` |
| `theme`, `citations`, `chrome`, `images`, `publicData`, `media` | unchanged from the bare projector: Markus theme, citations, shell options (GA4, consent mode, `title_template`, extra scripts), responsive images, search and latest JSON, originals |

### Sections

```json
"urls": { "style": "directory", "sections": {
  "essays": { "base": "essays", "label": "Essays" },
  "links":  { "base": "links", "label": "Links", "pages": false, "feed": false }
} }
```

An item's section comes from its CMS path (`essays/slow-water`). A section lists its entries at `/<base>/`
(paginated at `/<base>/page/N/`) and only when it has entries. `pages: false` makes a link-only section: items have
no page, appear in listings as cards that link to `linkField` (front matter `url` by default), and are never in
the sitemap or the feeds. `feed: false`, `sitemap: false`, `listing: false` take a section out of that one view. `groupBy` (`week`, Monday start, or `month`) gives the listing view dated groups (`listing.groups`) which the default listing renders under headings, `archive` (`{by: month|year, base, description}`) adds one page per month or year that has entries at `/<section>/<archive base>/<YYYY-MM>/` (in the sitemap, each with its own inputs), `pageSize` overrides the site's page size for the section, `description` is its listing's meta description, and `listEmpty: true` keeps its listing page when it has no entries (by default an empty section has no page).
Items in a section that is not declared are ignored; items with no section are root pages (`/about.html`).

### Entries

Every view (listings, tags, feeds, sitemap, hooks) reads one extended public entry model built from item summaries,
never from bodies: `title`, `summary_text` (front matter `description`, `summary`, `dek`, `standfirst`, `excerpt`
or `blurb`), `date`, `updated` (front matter `updated`, `modified`, `lastmod`, else the published time), `image`
(`image`, `cover`, `ogImage`, `thumbnail`), `authors` (`authors` or `author`), `type`, `canonical`, `tags`,
`section`, `feed_eligible` (not `feed: false`, in a feeding section, has a page), `noindex` (`noindex: true`,
`robots: noindex` or `draft: true`), `listed`, and the raw `data` for hooks.

## URL policy

`urls.style` decides the shape of every page: `html` writes `x.html`, `directory` writes `x/index.html`. With
`directory`, the edge function also redirects `/x.html` to `/x/` (except `/404.html`). Aliases on an item and slug
renames become exact redirects in the KeyValueStore as before. `redirects.exact` adds fixed ones.

**Pattern redirects are data.** `redirects.patterns` rules such as

```json
{ "pattern": "^/blog/([^/]+)/$", "to": "/articles/$1/" }
```

are compiled into the CloudFront Function at deploy time (`amplify/publication/redirect-rules.ts`), after the
exact-match lookup and before the index rewrite. Patterns must be anchored (`^...$`), may use groups `$1`..`$9`,
and may not use named groups, lookbehind or inline flags (Python and JavaScript read those differently). No site
writes its own edge function for redirects.

## Environment guard

The staging guard lives in config. `site.productionUrl` names the one production origin. The projector's own origin
comes from `PAPYRUS_SITE_PUBLIC_URL`; `PAPYRUS_SITE_ENV=production` (or any other value) overrides. Anything that is
not the production origin is **guarded**: every page gets `<meta name="robots" content="noindex, nofollow">`,
`robots.txt` is `Disallow: /`, and canonical links use that environment's own origin. A site that declares no
`productionUrl` and sets no `PAPYRUS_SITE_ENV` has nothing to guard and behaves as production. `environment.guard:
false` switches it off.

## The head

One builder writes the head of every page, in this order: font links, icons and manifest, theme colours, feed
autodiscovery (RSS and Atom), sitemap link, robots meta, description, canonical, Open Graph (with image width and
height when known), Twitter card, `article:*` times and tags, JSON-LD (`Article` or the mapped type, with
`datePublished` and `dateModified`, authors, publisher; plus `BreadcrumbList`), then whatever the `head_extra` hook
returns. Description falls back from the entry summary to the first paragraph to the site description. The image
falls back from the entry's cover to the first image in the body to `seo.defaultImage`. JSON-LD escapes `</`.

## Sitemap, robots, 404

`sitemap.xml` (or the index form) lists the home page, every entry with a page that is not `noindex`, listing page
1 of each section, tag pages, custom pages, with `<lastmod>` from the entry's `updated`. Drafts, the 404 page and
link-only items are excluded. With no known origin the sitemap is an empty `urlset` rather than relative URLs.
`404.html` is always generated, at that key, `noindex`.

## Feeds

`feed.xml` (RSS 2.0) and `atom.xml` (Atom 1.0) are rendered from one selection: feed-eligible entries, newest
first, `feeds.count` of them. Both carry permanent URLs as ids, categories, and `<lastBuildDate>` / `<updated>` from
the newest entry. **Withdrawal:** an item that is unpublished, or becomes ineligible (`feed: false`, `draft: true`),
leaves the selection and the next projection removes it from both files and the search data; the page's own
fate is separate (a withdrawn item's alias can redirect). An item that returns keeps its id.

## Listings and tags

A flat site has one listing at `/<listings.path>/`; a sectioned site has one per section. `pageSize` entries per
page, with `featuredCount` extra on page 1. Tag pages (`/tags/`, `/tags/<tag>/`) merge tags that differ only in
case. The generated home page lists the latest `homeCount` entries and links onward. An authored item named `index`
at the root replaces it.

Dependencies are declared, so incremental projection is exact: an item page depends on itself and the shared
settings (plus other sections' entries only if `components.itemPagesDependOn` says so); a listing page depends on the
card fields of exactly the entries it shows, its page number and page count; feeds and the sitemap on their own
bytes. Editing only a body writes only that article. A test applies random publish, edit and unpublish operations
and asserts the incremental result equals `project --all`.

## Components

Defaults, all accessible: a skip link to `<main id="main">`, a `nav aria-label="Site"` with `aria-current="page"`
(and an `aria-expanded` menu button with `nav.disclosure`), breadcrumbs, a pager with `rel="prev"`/`rel="next"`,
byline and `<time datetime>`, cards, footer columns, a tag list. `css/markus-components.css` gives them a baseline
(focus ring, reduced motion, skip-link behaviour) driven by `--papyrus-*` custom properties; your theme loads after
it and wins.

## Theme

`web/css/site-theme.css` is the only stylesheet you write. Use the Markus vocabulary (`markus-*` classes) and the
component classes above, define tokens as custom properties on `:root` with a dark override under
`prefers-color-scheme`, and keep brand files (logo, icon, share card) in `web/assets/`. The shell loads, in order,
`css/markus-vendor.css`, `css/markus-components.css`, `css/site-theme.css`, all cache-busted with the one version
token.

## Hooks

`"hooks": "hooks.py"` names a module in `web/`. Only these functions are called; any other public function is an
error (prefix helpers with `_`):

| Hook | Receives | Returns |
|---|---|---|
| `masthead(page)` | the page | the header block |
| `footer(page)` | the page | the inside of the footer |
| `card(entry, page)` | an entry | one card in a listing |
| `head_extra(page)` | the page | raw markup appended to `<head>` |
| `item_decorator(html, summary)` | the converted article, the item summary | the article HTML |
| `derive(summary)` | the item summary | a dict of derived fields (a tier, a week, a shape); available as `entry.derived`, part of every fingerprint, and how a site picks which row or card component renders |
| `page_body(page)` | the page | the whole body, or `None` for the default |

`page` is a `StandardPage`: `kind` (`item`, `home`, `listing`, `archive`, `tags`, `tag`, `custom`, `showcase`, `not_found`), `path`, `title`,
`entry`, `fragment`, `listing` (the slice, page numbers), `custom_id`, `entries`, `summaries`, `settings`,
`environment`, `head`, plus `skip_link` and the `components` module. `papyrus_content.projection.standard.fragments` has `article_body(fragment)` (the article without Markus's wrapper and header), `lede_of` and `first_image_of`. A site with typed content (its own card
fields, link-only items, special pages) builds its model from `page.summaries` and composes pages in `page_body`.
A hook that is handed `page` can read any entry, so by default every page depends on all entries and listings on all their fields. Narrow that with a module-level `DEPENDS_ON`: a list of section names (`@root` is the items with no section), `[]` for nothing, or a dict keyed by page id (`home`, `item`, `listing:<section>`, `listing:flat`, `tags`, `tag`, `archive:<section>`, `showcase`, `custom:<id>`, `not_found`, with `"*"` as the fallback) when pages depend on different things.
A hooks module's source and its sibling modules are part of every page's inputs, so editing them re-renders.

## Showcase (logo wall)

`"showcase": { "section": "showcase", "path": "built-with", "title": "Built with Papyrus", "kinds": { "anthus": "Built by Anthus", "design-partner": "Design partners", "customer": "Customers" } }`
turns every published item of the `showcase` section into one tile on a generated page at `/built-with/`. The data
is content, managed in the CMS: front matter `name` (or the title), `logo` (image path or URL; the name is the text
fallback), `logoAlt`, `url` (http or https only; anything else is skipped), `kind` (one of the configured kinds;
unknown kinds go under "More") and `order` (lower first, then name). The page is one heading and one `<ul>` per kind,
a responsive CSS grid of links with lazy-loaded images and `rel="noopener"`; names are escaped. Showcase items have
no pages of their own and are not in listings, feeds or the sitemap. A `page_body` hook sees `page.kind == "showcase"`
and `page.showcase` (the sorted `ShowcaseSite` records) and can use `showcase.logo_wall(...)` inside its own layout.

## Migration checklist

1. Copy `web/projection.json`: `site`, `urls` (style and sections to match today's URLs), `nav`, `footer`, `seo`,
   `feeds`, `fonts`, `icons`, `redirects`.
2. Set `site.productionUrl` and make sure `PAPYRUS_SITE_PUBLIC_URL` is set per environment.
3. Move the stylesheet to `web/css/site-theme.css`; map any private classes onto the component classes or keep them
   in a hook.
4. Replace the site projector with settings; keep only logic that needs a hook, in `hooks.py`.
5. Move hand-written edge redirects to `redirects.patterns`; delete the per-site edge function.
6. Move editorial values (descriptions, dates, tags, authors, aliases, cover images) into item front matter in the
   CMS.
7. Remove `publication.projector` from `papyrus.config.ts`; keep `staticDir`.
8. Project the old and the new site from the same published data (`papyrus ops content project --all --out DIR`)
   and compare every URL: status, normalised DOM, head metadata, sitemap URL set, redirects, feed items. Allow-list
   intentional differences with reasons (Atom added, `lastmod` added).
9. Deploy the edge change (it re-reads `projection.json`) together with the first projection.

## Extending the entry model

Entries carry the item's raw front matter as `entry.data` and a `derived` map from the `derive` hook, both part of
the dependency fingerprints, so a new per-item field (a content shape, a shelf life, a pin-until date) reaches
hooks, cards and listings without a change to the model. Ordering is one function (`entries.newest_first`) and
selection is the `listed` flag plus section options, so pin and shelf-life rules are additions at those two seams.
