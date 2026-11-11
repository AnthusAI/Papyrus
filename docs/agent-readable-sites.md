# Agent-readable sites

Status: Live for Markus sites (static, served from S3 and CloudFront). Every item below is on by default unless it says otherwise.

A Markus site publishes the same content in forms that software can read without scraping HTML. This page is the one place that lists them, what turns each off, and what is not built. The full projection reference is [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md); this page does not repeat it.

## What a site publishes

| Output | Default | Turned off by |
| --- | --- | --- |
| Markdown twin of every page | on | `agents.markdown: false` |
| `/llms.txt` | on | `agents.llmsTxt: false` |
| `/llms-full.txt` | on | `agents.llmsFull: false` |
| `Accept: text/markdown` negotiation | on | `agents.markdown: false` |
| Copy Markdown and View as Markdown | on | `pageActions.enabled: false` |
| Open in ChatGPT, Claude, Perplexity | off | opt in with `pageActions.ai` |
| RSS and Atom feeds | on | `feeds.formats` |
| `sitemap.xml` | on | (always written) |
| `robots.txt` | on | (always written) |
| JSON-LD and Open Graph | on | breadcrumbs only: `seo.breadcrumbs: false` |

## Markdown twins

Every published page has a `.md` twin next to it: `x.html` has `x.md`, `x/index.html` has `x/index.md`, and the home page has `index.md`. An article twin holds the title, summary, authors, dates and canonical URL, then the Markus source without front matter, every directive as written (`::image` with all its attributes). The twin is Markus; the `.md` extension and `text/markdown` type stay because Markus is a Markdown superset. An authored page (a `pages` entry with `source`), the home page and a section front page are templates, not articles: their twin says what the page shows (see [Twins of authored pages](#twins-of-authored-pages)). An authored page is listed in `llms.txt` and `llms-full.txt`, and has the page actions. On a directory-style site `/x.md` is served from `x/index.md`. A listing, archive, tag or home twin is a Markdown list of links to the other twins. HTML pages advertise their twin with `<link rel="alternate" type="text/markdown">`.

Which pages get no twin:

- the 404 page;
- any entry marked `noindex` (including drafts) and custom pages marked `noindex`;
- every page, if `agents.markdown` is off.

A page copied verbatim with `static.copy` has no generated twin. The site can ship its own and list the route in `sitemap.extra`; see "Hand-published routes" in [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md#agent-readable-pages).

## Every Markdown output is Markus source

Whatever serves the Markdown of an article to a reader or an agent serves the Markus source as written: `::image{src=… alt=… caption=…}` with all its attributes. Nothing flattens a directive into plain Markdown. In an article, `::include` and `::raw` regions are left out, because they place markup that has no source text, except the knowledge blocks and home-page components, which stay as written. A page file is different: its `::band`, `::column`, `::button`, `::island` and `::include` lines are a template for the HTML page, and the twin of such a page says what the page shows (PPY-0db38f, below). The audit (PPY-b2e95d), one test per row:

| Path | File(s) | Before | After | Test |
| --- | --- | --- | --- | --- |
| Item twin (`x.md`) | `projection/standard/markdown.py` `item_markdown`, `blocks.twin` | Directives kept (5.19.0) | Same | `test_markus_everywhere.py::test_item_twin_keeps_the_image_directive_and_drops_only_the_front_matter` |
| Authored page twin | `projector.py` `_authored_markdown`, `page_twin.py` | Page blocks and includes kept as written (5.19.0), so a reader saw `::band{size="bare"}` and `::include{kind="references" ...}` | What the page shows: includes as lists of titles and links, a button as a link, an island as its summary, no band or column | `test_authored_page_twin_says_what_its_page_blocks_show`; `features_backend/markus-twins.feature`, `features_backend/page-twins.feature` |
| Home twin | `markdown.py` `home_markdown`, `projector.py` | Wrote a title and description of its own in front of the source, so a home written as page blocks showed a second `# Title` before `::band` | What the source shows (as an authored page); title only when the source has none | `test_home_twin_says_what_its_page_blocks_show_without_a_second_title`, `test_home_twin_adds_the_title_only_when_the_source_has_none` |
| Listing, archive, tag and tags twins | `markdown.py` `listing_markdown` | Link lists to the `.md` twins | Same (no body to carry; each link leads to a Markus twin) | `test_listing_and_tag_twins_are_link_lists_to_the_markus_twins`, `test_listing_twin_lines_link_to_the_twin_not_the_html` |
| `Accept: text/markdown` | `amplify/publication/redirect-and-index.js` | A URI rewrite to the twin object | Same object, now checked against every twin of the golden sites | `scripts/test-redirect-rules.ts` "negotiated Markdown for every page…" |
| `llms.txt` | `markdown.py` `llms_txt` | Links to the twins | Same | `test_llms_txt_links_to_the_twins` |
| `llms-full.txt` | `markdown.py` `llms_full_txt`, `projector.py` | Twin bodies (5.19.0) | Same | `test_llms_full_carries_page_blocks_as_written`, `test_llms_full_carries_the_image_directive` |
| Copy Markdown | `assets/papyrus-page-actions.js` | Fetched the twin, but added a second `# Title` in front of any twin that did not start with `# ` (every page written as page blocks) | Copies the twin; adds a title only when the twin has no H1 anywhere | `scripts/test-page-actions.ts` "copy gives a page written as page blocks exactly as the twin…" |
| View as Markdown | `page_actions.py` | Links to the twin | Same | `test_page_actions_point_at_the_twin_and_ai_links_carry_only_the_page_url` |
| Open in ChatGPT, Claude, Perplexity | `page_actions.py` `ai_links` | Hand over the page URL in a short prompt, never the body | Same | `test_ai_prompt_targets_never_carry_the_page_body` |
| RSS and Atom feeds | `feeds.py` | Front matter summary as plain text; no Markdown, no body | Same (nothing to change) | `test_feeds_carry_only_the_front_matter_summary` |
| Markus docs sites | `markus_renderer/docs_site.py` `twin_text`, `write_agent_outputs` | The staged Markus page (MkDocs dialects already converted to directives) | Same | `test_markus_docs_site.py::test_twins_and_llms_full_carry_the_markus_source_with_directives_intact` |
| Public data JSON (`search-index.json`, `latest.json`) | `projection/public_data.py` | Front matter summary text; no body | Same (nothing to change) | none (read-only audit; owned by Data Parade) |
| `papyrus ops content export` | `markus_export.py` | Writes `bodyMarkus` as stored | Same | `test_markus_export.py::test_an_exported_body_keeps_its_image_directive_verbatim` |
| CMS app API routes (`app/api/*`) | `app/api` | None serves Markdown to readers | Same | none |

Out of scope, listed: the plain-text excerpts the editorial checks and the console chat use internally (`lib/editorial-checks-demo.ts`, `components/topic-steering-workspace.tsx`) are for the editor's own UI, not reader output.

## llms.txt and llms-full.txt

`/llms.txt` follows llmstxt.org: an H1 with the site name, a blockquote from the site description, H2 sections of links to the twins, and an Optional section with the feeds, the sitemap and `llms-full.txt`.

`/llms-full.txt` is the published content in one file.

- It is written only when the site has between 1 and `agents.llmsFullMaxItems` pages (default 200). Above that it is omitted.
- It stops before it would pass `agents.llmsFullMaxBytes` (default 1,000,000 bytes) and ends with a note pointing to `/llms.txt`.
- Each section in `llms.txt` lists at most `agents.llmsMaxLinks` links (default 200).
- Neither file is written on a non-production origin (see "robots.txt" below).
- `llmsTxt` and `llmsFull` require `agents.markdown`; turning Markdown off while leaving them on is a configuration error.

## Twins of authored pages

The twin of an authored page, of the home page when it is an item written as page blocks, and of a section front page with a `source` is built by `projection/standard/page_twin.py` from the same text the page is rendered from:

- `::band` and `::column` are layout and write nothing.
- `::button{href label}` is a Markdown link, with a site path made absolute.
- `::island` is its `summary` text, when it has one.
- `::raw` regions write nothing.
- `::include{kind="listing"}` is one list item per story, linking to the story's twin, from the same selection and order as the page.
- `::include{kind="references"}` and `::include{kind="threads"}` are the References and conversations the page places, a title linked to its address (a conversation links to its page when the site has `homePage.forum`, with its message count), a heading when the include has one, its `empty` text when there is nothing, and its `more` link. A Reference no editor has accepted is followed by "Recommended by Cyclotron, not yet accepted". They are chosen by the same functions as the page (`home_page_blocks.select_references`, `select_threads`, so a `section` attribute filters the twin exactly as it filters the page) with a ledger of their own, so the twin lists exactly what the page lists, in the same order, with no repeats across includes. Only the title, address and standing are written; authors, summaries, confidence and every other snapshot field stay out.
- `::include{kind="showcase"}` is the list of the logo wall's sites; `kind="form"` writes nothing.
- `::include{kind="block"}` (a site's own `block` hook, or a `knowledge-` block) is the block's markup reduced to its headings and one list item per distinct link. A block that links to nothing is its text. A hook needs no extra code to appear in the twin.
- Everything else, including `::image` and `:::` containers, is kept as written.

The twin is rewritten by the path that rewrites the page. Its input digest is the page's (includes' entries, the home-page snapshot, the knowledge snapshot), so an edit to a story an include shows, or a new snapshot, changes both. `home_page_reader_keys` names the twins and `llms-full.txt` with the pages, so `papyrus home-page snapshot` rewrites them too. Nothing scans a corpus to do it.

## Markdown in a browser

The twins are stored as `text/markdown; charset=utf-8`. Safari downloads that type, so a link to a twin ("View as Markdown", a shared link) saved a file instead of showing the text (PPY-40f96a). A CloudFront viewer-response function (`amplify/publication/markdown-content-type.js`) answers a browser, a request whose `Accept` lists `text/html` above `text/markdown`, with `text/plain; charset=utf-8`; a request that prefers or ties `text/markdown`, or names no type (`*/*`, none), still gets `text/markdown`. Only a response typed `text/markdown` is touched, there is no `Content-Disposition`, and the response adds `Vary: Accept`. The function runs after the cache, so the stored object, its cache key and every cached copy are unchanged and a browser cannot make an agent's cached response plain text or the reverse; the stored objects need no re-projection. The function is attached to distributions the site backend creates (`distribution.create`) and is in the hand-run edge templates (`infra/edge/s3-projection-cms.yaml`, `pilobol-us.yaml`, `threat-intelligence.yaml`, and the Anth.us viewer-response function in `anth-us-s3.yaml`); a template change reaches a site when its edge stack is next deployed. Test: `scripts/test-markdown-content-type-function.mjs`, `features/markdown-twin-display.feature`.

## Accept: text/markdown

A request whose `Accept` header prefers `text/markdown` over `text/html` (by q-value) gets the page's `.md` twin from the same URL. The negotiation runs in the CloudFront viewer-request function (`amplify/publication/redirect-and-index.js`) and is switched on at deploy time for every standard front end site that does not set `agents.markdown: false`. Markdown and HTML are cached separately.

Where it does not work: a site served by an Amplify managed edge, and the GitHub Pages documentation sites. They serve HTML for every `Accept`. Their `.md` twins and `llms.txt` still work by direct URL. The current list of sites is in [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md#agent-readable-pages).

## Page actions

Article pages that have a twin get an actions group above the article (`placement: "header"`) or after it (`"aside"`).

- **Copy Markdown** and **View as Markdown** are on by default.
- **Open in ChatGPT**, **Open in Claude** and **Open in Perplexity** are off by default. Opt in with `pageActions.ai`, a list drawn from `chatgpt`, `claude`, `perplexity`. Each link opens the provider's new-chat URL with a short prompt that names the page URL. The page body is never put in a URL.
- `pageActions.display: "icons"` switches to compact Lucide icon buttons and unlocks **Post on X**, **Post on Reddit** and a **Share** popup (`actions: ["view", "copy", "x", "reddit", "share"]`). Post links carry only the title and address. A site with its own article template places the group with `page.article_actions()`.
- `pageActions.everywhere: true` (off by default) gives the home page, listings, section and collection fronts, tag and archive pages, paged list pages and standing pages the same group, each with its own title, canonical address and Markdown twin, and only where the twin exists. `page.article_actions()` returns the markup on those pages too. See [building a static site](building-a-papyrus-static-site.md#actions-on-every-page-pageactionseverywhere).
- The links need an absolute page URL, so they do not appear on a site with no known origin.

Details are in [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md#page-actions).

## Feeds, sitemap, robots

- **Feeds.** RSS 2.0 at `feed.xml` and Atom 1.0 at `atom.xml`, from one selection of feed-eligible entries (newest first, `feeds.count`, default 30). The head advertises them.
- **Sitemap.** `sitemap.xml`, or an index plus `sitemap-0.xml` with `sitemap.style: "index"`. It lists pages that are not `noindex`.
- **robots.txt, production.** `User-agent: *`, `Allow: /`, any lines from `robots.extra`, and a `Sitemap:` line. That is open to every crawler, AI crawlers included. Papyrus does not block any crawler by default; to block one, add lines through `robots.extra`.
- **robots.txt, non-production.** Any origin that is not the `site.productionUrl` origin is guarded: `User-agent: *` and `Disallow: /`, `<meta name="robots" content="noindex, nofollow">` on every page, and no `llms` files. `environment.guard: false` switches the guard off.

## JSON-LD and Open Graph

Article pages carry JSON-LD (`Article`, or the type mapped in `seo.jsonLdTypes`), plus `BreadcrumbList` when `seo.breadcrumbs` is on and the origin is known. Pages carry Open Graph and Twitter card tags. The only switch for these in `projection.json` is `seo.breadcrumbs` for the breadcrumb data; the mapping keys are in `seo`.

## projection.json

Defaults shown. You only write what you change.

```json
{
  "agents": {
    "markdown": true,
    "llmsTxt": true,
    "llmsFull": true,
    "llmsFullMaxItems": 200,
    "llmsFullMaxBytes": 1000000,
    "llmsMaxLinks": 200
  },
  "pageActions": {
    "enabled": true,
    "placement": "header",
    "actions": ["copy", "view"],
    "display": "text",
    "ai": [],
    "prompt": "Read {url} and help me with it.",
    "types": []
  },
  "feeds": { "formats": ["rss", "atom"], "count": 30 },
  "robots": { "extra": [] },
  "seo": { "breadcrumbs": true }
}
```

To turn agent output off entirely, set `"agents": { "markdown": false, "llmsTxt": false, "llmsFull": false }`. To add one AI link, set `"pageActions": { "ai": ["claude"] }`. `pageActions.types` is a list of extra entry types that get actions; leaving it out means the listed types only.

## Not built yet

- An MCP server for a publication, and WebMCP in the page. Neither exists. They are on the roadmap as PPY-2bc3e8.
