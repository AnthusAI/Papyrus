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
| `urls` | `style`: `html` (`/x.html`, default) or `directory` (`/x/`). `sections`: `{ "<section>": { base, label, description, pages, listing, feed, sitemap, linkField, pageSize, listEmpty, sort } }`. Leave it out for a site without sections |
| `nav` | `links: [{label, href, cta, external, children}]` (`external` adds `rel="noopener"`; `children: [{label, href}]` makes a dropdown group, see "Header and footer options"), `disclosure` (a menu button for narrow screens), `homeLabel`, `brandHtml` (trusted markup inside the wordmark link) |
| `footer` | `columns: [{title, links}]`, `text`, `family` (the Anthus family footer, see "Header and footer options") |
| `seo` | `defaultImage`, `imageSize: [w, h]`, `twitterSite`, `twitterCreator`, `jsonLdTypes: {section-or-type: "NewsArticle"}`, `defaultJsonLd`, `publisherName`, `breadcrumbs` |
| `sitemap` | `style`: `single` (`/sitemap.xml`) or `index` (`/sitemap-index.xml` + `/sitemap-0.xml`); `lastmod`; `tags`; `extra`: paths (starting with `/`) to list that core does not generate, such as `static.copy` routes |
| `robots` | `extra`: extra lines |
| `feeds` | `formats` (`rss`, `atom`), `count` (30), `rssPath`, `atomPath`, `title` |
| `listings` | `pageSize` (10), `featuredCount`, `path` (the flat listing base, `archive`), `homeCount`, `tags`, `tagBase`, `types` (entry types that are listed, `["article"]`) |
| `fonts` | `stylesheet` (a font CSS URL; adds the `preconnect` links), `preconnect` |
| `icons` | `icon`, `iconType`, `appleTouch`, `manifest`, `themeColor`, `themeColorDark` |
| `environment` | `guard` (default `true`) |
| `redirects` | `exact: {"/old/": "/new/"}`, `patterns: [{pattern, to, status, except}]` |
| `pages` | custom generated pages: `[{id, path, title, description, dependsOn, sitemap, noindex, form}]`; the body comes from the `page_body` hook |
| `static` | `copy`: directories of `web/` published verbatim at the site root (an exported app, retained routes). They are never owned by the projector, so a reconcile does not delete them; css and assets stay reserved |
| `showcase` | a logo wall fed from published items: `{section, path, title, description, kinds}` (see "Showcase") |
| `forms` | public forms as data (see "Forms"): `{ "<id>": {title, fields, endpoint, submitLabel, honeypot, closedNotice, successText, failureText} }` |
| `agents` | agent-readable output, all on by default: `markdown` (a `.md` twin per page), `llmsTxt`, `llmsFull`, `llmsFullMaxItems` (200), `llmsFullMaxBytes` (1000000), `llmsMaxLinks` (200) |
| `pageActions` | copy / view / open-in actions on article pages: `{enabled, placement (header\|aside), actions (copy, view), ai (chatgpt, claude, perplexity), prompt}` |
| `components` | `itemByline`, `breadcrumbs`, `itemPagesDependOn` |
| `values` | `{ "name": "text or number" }`: the `{{name}}` tokens of page blocks (see "Page blocks") |
| `islands` | `{script, stylesheet}`: the site bundle that mounts islands, and an optional stylesheet linked on every page (see "Islands") |
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
the sitemap or the feeds. `feed: false`, `sitemap: false`, `listing: false` take a section out of that one view. `groupBy` (`week`, Monday start, or `month`) gives the listing view dated groups (`listing.groups`) which the default listing renders under headings, `archive` (`{by: month|year, base, description}`) adds one page per month or year that has entries at `/<section>/<archive base>/<YYYY-MM>/` (in the sitemap, each with its own inputs), An item named `index` in a declared section is that section's **introduction**: it has no page of its own; its body (and title and description) head the section's listing at `/<base>/`, and a line `{{ section listing }}` in it places the generated cards (otherwise they follow the introduction). `sort: "order"` lists a section by front matter `order` (ascending, then title) instead of newest first. `pageSize` overrides the site's page size for the section, `description` is its listing's meta description, and `listEmpty: true` keeps its listing page when it has no entries (by default an empty section has no page).
Items in a section that is not declared are ignored; items with no section are root pages (`/about.html`).

### Entries

Every view (listings, tags, feeds, sitemap, hooks) reads one extended public entry model built from item summaries,
never from bodies: `title`, `summary_text` (front matter `description`, `summary`, `dek`, `standfirst`, `excerpt`
or `blurb`), `date` (front matter `date`, ISO or written out as in "Sunday, September 6, 2026"; else the published day), `updated` (front matter `updated`, `modified`, `lastmod`, else the published time), `image`
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
returns. The JSON-LD `headline` is the entry title; a page built through `PageHead` with a title template ("Title | Site") sets `headline` to keep it plain. Description falls back from the entry summary to the first paragraph to the site description. The image
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
| `body_class(page)` | the page | classes added to `<body>` after `chrome.body_class` |
| `item_decorator(html, summary)` | the converted article, the item summary | the article HTML |
| `derive(summary)` | the item summary | a dict of derived fields (a tier, a week, a shape); available as `entry.derived`, part of every fingerprint, and how a site picks which row or card component renders |
| `page_body(page)` | the page | the whole body, or `None` for the default |

`page` is a `StandardPage` (on a section's first listing page `fragment` is the introduction, converted and not decorated; `fragments.with_listing` places a listing in it): `kind` (`item`, `home`, `listing`, `archive`, `tags`, `tag`, `custom`, `showcase`, `not_found`), `path`, `title`,
`entry`, `fragment`, `listing` (the slice, page numbers), `custom_id`, `entries`, `summaries`, `settings`,
`environment`, `head`, plus `skip_link` and the `components` module. `papyrus_content.projection.standard.fragments` has `article_body(fragment)` (the article without Markus's wrapper and header), `lede_of` and `first_image_of`. A site with typed content (its own card
fields, link-only items, special pages) builds its model from `page.summaries` and composes pages in `page_body`.
A hook that is handed `page` can read any entry, so by default every page depends on all entries and listings on all their fields. Narrow that with a module-level `DEPENDS_ON`: a list of section names (`@root` is the items with no section), `[]` for nothing, or a dict keyed by page id (`home`, `item`, `listing:<section>`, `listing:flat`, `tags`, `tag`, `archive:<section>`, `showcase`, `custom:<id>`, `not_found`, with `"*"` as the fallback) when pages depend on different things.
A hooks module's source and its sibling modules are part of every page's inputs, so editing them re-renders.

## Page blocks

Marketing pages need full-width sections, columns, calls to action and interactive widgets that Markus does not
describe. Page blocks are line-level directives that the standard projector handles **before** Markus runs. They are
opt-in: a file with no `::band` line is converted exactly as before. Each directive sits alone on its line. They work for
sites whose content is a directory of Markdown files (`project --all --from-dir`); the CMS save path validates bodies
with Markus alone and still rejects them.

```markdown
::band{id="start" tone="card" size="hero" eyebrow="Open source" columns="home"}
# {{headline}}

Text between directives is ordinary Markus.

::button{href="/start/" label="Start" size="lg"}
::button{href="https://example.org/" label="Source" variant="secondary"}

::column{panel="card"}
::island{name="DecisionCarousel" height="24rem"}
```

| Directive | Attributes | Output |
|---|---|---|
| `::band` | `id`, `tone` (`background` default, `card`, `muted`), `size` (`standard` default, `hero`, `bare`), `eyebrow`, `columns` (a layout name for your CSS) | starts a full-width section that lasts until the next `::band` |
| `::column` | `panel` (`card`) | starts the next column of the band |
| `::button` | `href`, `label`, `size` (`default`, `lg`), `variant` (`default`, `secondary`) | a link; consecutive lines (blank lines between them allowed) share one row |
| `::island` | `name` (required), `height` (`20rem`, `300px`, `50vh`), any other attribute | a mount point (see "Islands") |

A band renders as

```html
<section class="markus-band" id=".." data-tone=".." data-size=".." data-layout="..">
  <div class="markus-band-inner">
    <p class="markus-band-eyebrow">..</p>
    <div class="markus-columns" data-count="2">
      <div class="markus-column">..</div>
      <div class="markus-column" data-panel="card">..</div>
    </div>
  </div>
</section>
```

(`id` and `data-layout` only when given.) `size="bare"` emits only the band's contents, with no wrapper, for components
that bring their own section. Buttons are `<p class="markus-actions"><a class="markus-button" data-size=".." data-variant=".." href="..">label</a>...</p>`;
only `http(s):`, `mailto:`, site-absolute (`/x`) and `#fragment` hrefs are accepted, and everything is escaped. Text
between directives is converted by Markus one segment at a time and joined, so the page has no `<article>` wrapper and no
Markus header; the band markup is the page. A page that uses bands must start with a `::band` line (after the front
matter). Unknown attributes, tones, sizes and variants are errors that name the file. Directives inside code fences are
text. `::island` and `::button` also work inside a Markus `:::` container (a card, a column): there they are swapped in
after the container is converted; `::band` and `::column` stay top-level only.

**Values.** `{{name}}` is replaced, in text and in directive attributes, before conversion, from the top-level
`values` object of `projection.json` (strings or numbers). A name that is not defined is a build error naming the file
and the token. A site with no `values` leaves every `{{...}}` alone (and `{{ section listing }}`, with its spaces, is
never a value). Values are part of the shared fingerprint, so changing one re-renders every page.

**Agent-readable twins.** For a page with bands, the `.md` twin and `llms-full.txt` drop the band and column markers,
turn buttons into Markdown links on one line (`[Start](/start/) · [Source](https://example.org/)`), omit islands and
have tokens replaced.

The baseline `css/markus-components.css` styles bands, columns, panels and buttons through `--papyrus-band-*`,
`--papyrus-button-*`, `--papyrus-rule` and `--papyrus-radius`; your theme restyles them and may key on `data-layout`.

## Islands

An island is a mount point for interactive code the site owns (a chart, a carousel). Core only finds the mount
points and calls the site's code:

```json
"islands": { "script": "assets/islands.js", "stylesheet": "css/islands.css" }
```

Both files are read from `web/`; a missing file is an error. A page that contains at least one
`<div class="papyrus-island" data-island="Name" data-props='{...}'>` (from `::island`, or emitted by a hook) gets, after
the body, `_plugins/papyrus-islands-v1.js` and `<script type="module" src="/assets/islands.js?v=TOKEN">`, cache-busted like
the other assets. Pages without an island get neither. The stylesheet, when configured, is linked on every page.

The contract: the site bundle assigns `window.papyrusIslands = { ...window.papyrusIslands, Name(element, props) { ... } }`
(merge, do not replace). On `DOMContentLoaded` the runtime calls `window.papyrusIslands[name](element, props)` once for each
`[data-island]`; `props` is the parsed `data-props` JSON (the `::island` attributes other than `name` and `height`).
An unknown name logs a console warning and never throws; an island that throws is logged and does not stop the others.
`height` becomes `style="min-height:.."` so the page does not jump when the island mounts.

## Header and footer options

**Brand.** `nav.brandHtml` is trusted markup (a logo and a word) placed inside the wordmark link instead of the site
name; the link keeps `aria-label="<site name>, home"`. Without it the wordmark is the escaped site name as before.

**Links.** `nav.links[].external: true` adds `rel="noopener"` (the target is not changed). A link with `children:
[{label, href, external}]` and no `href` renders a group:
`<details class="markus-nav-group"><summary>Label</summary><div class="markus-nav-group-links">...links...</div></details>`.
On narrow screens it is an expandable list inside the menu; on wider screens `markus-components.css` shows the links as a
dropdown while the group is hovered or focused (browsers without `::details-content` fall back to click). There is no
script beyond the existing `nav.disclosure` one. Footer column links accept `external` too.

**Family footer.** `footer.family` renders the footer of the npm package `anthus-footer` as static HTML and replaces the
default footer rendering (a `footer` hook still wins):

```json
"footer": { "text": "Open-source decision engine.", "family": { "siteId": "tactus", "byline": "Designed by us" },
            "columns": [{ "title": "Resources", "links": [{ "label": "Docs", "href": "/docs/" }] }] }
```

`family` keys, all optional: `siteId` (a key of the registry such as `tactus`; its label is the site's heading), `name`
(heading when the site is not in the registry; default the site name), `tagline` (a small line above the heading; none by
default), `description` (default `footer.text`, then the package's sentence), `byline` (`© Anthus AI Solutions`, linked to
the company site). The markup has three parts, as in the package: the site's own band (`papyrus-family-footer-local`: the
`-intro` with heading and description, then one column per `footer.columns` entry); the "Made by Anthus AI Solutions" band
(`-band`: the `-groups` Products, Open source we use and Research, each site with its one-line description, then the
byline); and the `-community` links with descriptions (Contact us, GitHub, LinkedIn). The registry is `anthus_sites.json`
next to the code, data mirrored from the package's `src/sites.js`; the package is the source of truth, so update the file
from it. Only sites that are `live` and shown in the footer appear, in the package's order, the current site included
(a `siteId` of `anthus` adds the "Anthus" company column and drops "Made by"). Colours come from
`--papyrus-family-footer-background` (the site band), `-accent-background` (the platform band), `-text`, `-muted-text`,
`-link`, `-max-width` and `-font-family`; the defaults are the package's dark theme, so a site overrides only its colours.

## Showcase (logo wall)

`"showcase": { "section": "showcase", "path": "built-with", "title": "Built with Papyrus", "kinds": { "anthus": "Built by Anthus", "design-partner": "Design partners", "customer": "Customers" } }`
turns every published item of the `showcase` section into one tile on a generated page at `/built-with/`. The data
is content, managed in the CMS: front matter `name` (or the title), `logo` (image path or URL; the name is the text
fallback), `logoAlt`, `url` (http or https only; anything else is skipped), `kind` (one of the configured kinds;
unknown kinds go under "More") and `order` (lower first, then name). The page is one heading and one `<ul>` per kind,
a responsive CSS grid of links with lazy-loaded images and `rel="noopener"`; names are escaped. Showcase items have
no pages of their own and are not in listings, feeds or the sitemap. A `page_body` hook sees `page.kind == "showcase"`
and `page.showcase` (the sorted `ShowcaseSite` records) and can use `showcase.logo_wall(...)` inside its own layout.

## Content in the repository (no CMS)

A site whose Markdown lives in its repository and is built by CI projects the same way, with no CMS:

```
papyrus ops content project --all --from-dir content --static-dir web --out dist
```

Every `.md` under `content/` is a published item (the first directory is its section; front matter `type` defaults to
`article`, `type: page` makes a root page, `aliases` become redirects). Redirects are reported by the CMS path only;
a repository-built site keeps them in `projection.json` (`redirects`). Directories below the section nest the slug:
`content/examples/basics/first.md` is the item `basics/first` of the `examples` section, at `/examples/basics/first/`
(`examples/basics.md` is `/examples/basics/`). Sync `dist/` to the bucket as before.

## Forms

`forms` defines a public form as data: `fields` (`name`, `label`, `type` of `text`, `email`, `textarea` or `select`,
`required`, `options`, `autocomplete`, `help`), a `honeypot` field name (default `website`), texts, and an `endpoint`
(https or a site path). A custom page with `"form": "<id>"` shows it; a hook can place it with `page.form("<id>")`.
With an endpoint, `_plugins/papyrus-form-v1.js` posts the fields as JSON plus `page` (the page path) and the honeypot
field, and reports success only for a 2xx answer (anything else shows `failureText`). **With `endpoint: null` the form
is a disabled fieldset under a "not open yet" notice: nothing can be submitted and success is never faked.** The
receiving endpoint (shared, rate-limited, bot-protected; submissions as newsroom Messages) is separate backend work
(PPY-caf9be).

## Agent-readable pages

Every page has a Markdown twin built from the same published content: `x.html` has `x.md`, `x/index.html` has
`x/index.md`, the home page `index.md`. An article twin is its facts (title, summary, authors, dates, canonical URL)
and its Markus source without front matter (`::image` becomes a Markdown image; other directives pass through). A
listing, archive, tag or home twin is a Markdown link list pointing at the other `.md` URLs. HTML pages advertise
their twin with `<link rel="alternate" type="text/markdown">`; the objects are stored as
`text/markdown; charset=utf-8`. The eligibility rules are the sitemap's and the feeds': only published pages, no twin
for a `noindex` entry or the 404 page.

`/llms.txt` follows llmstxt.org: an H1 with the site name, a blockquote from the site description, H2 sections of
links to the twins (one per section, or "Articles" for a flat site, then "Pages"), and an "Optional" section with the
feeds, the sitemap and `llms-full.txt`. `/llms-full.txt` is the whole published content in one file, produced only
when the site has at most `llmsFullMaxItems` pages and truncated at `llmsFullMaxBytes`. A guarded (non-production)
environment publishes no `llms` files. Everything is regenerated on publish: a twin with its page, `llms.txt` when a
title, summary or date changes, `llms-full.txt` whenever any item is republished (it is keyed on item versions, so a
body edit is seen; a republish that changes no visible field rewrites it with identical bytes).

**Content negotiation.** The shared CloudFront viewer-request function rewrites a request whose `Accept` prefers
`text/markdown` over `text/html` (by q-value, wildcards ignored) to the `.md` object before the cache lookup, so the
two representations cache separately. It is enabled at deploy time for every standard front end site that does not set
`agents.markdown: false`. A `Link: rel=alternate` response header is not added (S3 objects cannot carry one and no
response function is attached); the `<link>` in the HTML head is the discovery path.

## Page actions

Article pages (entries of a listed type that have a Markdown twin) get a small actions group, on by default, above the
article (`placement: "header"`) or after it (`"aside"`): a **Copy Markdown** button and a menu with **View as Markdown**
and, if `ai` lists them, **Open in ChatGPT / Claude / Perplexity**. Copy fetches the page's own `.md` twin (the file the
edge serves), adds the title and canonical URL when the twin lacks them, and confirms with an announced "Copied"; if the
Clipboard API is unavailable or refuses, it selects the text through `execCommand`, and failing that leaves a selected
textarea. The AI links open the provider's new-chat URL with a short prompt (`prompt`, default "Read {url} and help me
with it.") that names the page URL; the page body is never put in a URL. Everything happens on an explicit click; the
only reporting is a `page_action` event through the site's existing `gtag`, so consent mode applies.

Without JavaScript the markup is a list of links (View as Markdown, Open in ...) and the copy button stays hidden
(`visibility: hidden`, so it also stays out of the accessibility tree and keeps its space: no layout shift). With
JavaScript the links become a menu button following the ARIA menu pattern (Enter, Space, Arrow keys, Home, End, Escape,
Tab). Styling uses the `--papyrus-*` tokens, so light and dark themes follow the site's.

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
