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

Every published page has a `.md` twin next to it: `x.html` has `x.md`, `x/index.html` has `x/index.md`, and the home page has `index.md`. An article twin holds the title, summary, authors, dates and canonical URL, then the Markus source without front matter. A listing, archive, tag or home twin is a Markdown list of links to the other twins. HTML pages advertise their twin with `<link rel="alternate" type="text/markdown">`.

Which pages get no twin:

- the 404 page;
- any entry marked `noindex` (including drafts) and custom pages marked `noindex`;
- every page, if `agents.markdown` is off.

A page copied verbatim with `static.copy` has no generated twin. The site can ship its own and list the route in `sitemap.extra`; see "Hand-published routes" in [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md#agent-readable-pages).

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
