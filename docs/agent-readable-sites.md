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

Every published page has a `.md` twin next to it: `x.html` has `x.md`, `x/index.html` has `x/index.md`, and the home page has `index.md`. An article twin holds the title, summary, authors, dates and canonical URL, then the Markus source without front matter, every directive as written (`::image` with all its attributes, page blocks, and an island with its `summary` text). The twin is Markus; the `.md` extension and `text/markdown` type stay because Markus is a Markdown superset. An authored page (a `pages` entry with `source`) has the same kind of twin, is listed in `llms.txt` and `llms-full.txt`, and has the page actions. On a directory-style site `/x.md` is served from `x/index.md`. A listing, archive, tag or home twin is a Markdown list of links to the other twins. HTML pages advertise their twin with `<link rel="alternate" type="text/markdown">`.

Which pages get no twin:

- the 404 page;
- any entry marked `noindex` (including drafts) and custom pages marked `noindex`;
- every page, if `agents.markdown` is off.

A page copied verbatim with `static.copy` has no generated twin. The site can ship its own and list the route in `sitemap.extra`; see "Hand-published routes" in [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md#agent-readable-pages).

## Every Markdown output is Markus source

Whatever serves Markdown to a reader or an agent serves the Markus source as written: `::image{src=… alt=… caption=…}` with all its attributes, page blocks (`::band`, `::column`, `::button`), and an `::island` with its `summary` text. Nothing flattens a directive into plain Markdown. Only `::include` and `::raw` regions are left out, because they place markup that has no source text. The audit (PPY-b2e95d), one test per row:

| Path | File(s) | Before | After | Test |
| --- | --- | --- | --- | --- |
| Item twin (`x.md`) | `projection/standard/markdown.py` `item_markdown`, `blocks.twin` | Directives kept (5.19.0) | Same | `test_markus_everywhere.py::test_item_twin_keeps_the_image_directive_and_drops_only_the_front_matter` |
| Authored page twin | `projector.py` `_authored_markdown` | Page blocks kept (5.19.0) | Same | `test_authored_page_twin_keeps_its_page_blocks`; `features_backend/markus-twins.feature` |
| Home twin | `markdown.py` `home_markdown`, `projector.py` | Wrote a title and description of its own in front of the source, so a home written as page blocks showed a second `# Title` before `::band` | Source as written; title only when the source has none | `test_home_twin_keeps_the_page_blocks_without_a_second_title`, `test_home_twin_adds_the_title_only_when_the_source_has_none` |
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

## Accept: text/markdown

A request whose `Accept` header prefers `text/markdown` over `text/html` (by q-value) gets the page's `.md` twin from the same URL. The negotiation runs in the CloudFront viewer-request function (`amplify/publication/redirect-and-index.js`) and is switched on at deploy time for every standard front end site that does not set `agents.markdown: false`. Markdown and HTML are cached separately.

Where it does not work: a site served by an Amplify managed edge, and the GitHub Pages documentation sites. They serve HTML for every `Accept`. Their `.md` twins and `llms.txt` still work by direct URL. The current list of sites is in [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md#agent-readable-pages).

## Page actions

Article pages that have a twin get an actions group above the article (`placement: "header"`) or after it (`"aside"`).

- **Copy Markdown** and **View as Markdown** are on by default.
- **Open in ChatGPT**, **Open in Claude** and **Open in Perplexity** are off by default. Opt in with `pageActions.ai`, a list drawn from `chatgpt`, `claude`, `perplexity`. Each link opens the provider's new-chat URL with a short prompt that names the page URL. The page body is never put in a URL.
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
