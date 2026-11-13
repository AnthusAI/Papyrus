# Serving a site in several languages

Status: built in the engine (initiative PPY-82f150, epic PPY-756495); no site serves a second language yet. Plan: [docs/plans/multilingual-publishing.md](plans/multilingual-publishing.md). Specifications: `features_backend/language-serving.feature`, `features_backend/language-serving-settings.feature`, `features_backend/item-language.feature`.

A translation of a Story is a sibling Story (its lineage is `{primaryLineageId}--{language}`) joined to the original by its language group (`Item.language`, `Item.languageGroupId`, PPY-843a7c). This page covers what happens once such a localization is published: where it is served, what its page says about the other languages, and what each language's listings, sitemaps and links contain.

## The setting

There is one languages setting: the editorial check settings' `languages` (Administration > Editorial checks, stored in `EditorialCheckSettings`). `primary` and `enabled` say which languages the site writes in ([editorial checks](editorial-checks.md)). Three more keys say how they are served (`src/papyrus_content/language_serving.py`):

```json
{"languages": {
  "primary": "en",
  "enabled": ["en", "es-419", "zh-Hans"],
  "prefixes": {"es-419": "es", "zh-Hans": "zh"},
  "public": ["en", "es-419"],
  "slugs": {"es-419": "translated", "zh-Hans": "characters"}
}}
```

| Key | Meaning | Default |
| --- | --- | --- |
| `prefixes` | URL prefix of each enabled language other than the primary: a lowercase path segment (`es`, `zh`, `zh-hant`). Paths use the prefix; `<html lang>`, `hreflang`, `og:locale` and JSON-LD `inLanguage` use the tag. | the tag's base subtag, lowercased (`es-419` to `es`, `zh-Hans` to `zh`) |
| `public` | Languages the public site serves; the primary is always one. An enabled language that is not public is written, translated and checked, but its published localizations get no page (the plan's "preview" state). | only the primary |
| `slugs` | How a localization's slug is drafted at its first publish: `translated` (the translated title in plain letters), `characters` (the title in its own script; Chinese characters kept), `pinyin` (the title romanized by a romanizer the caller supplies), `primary` (the original's slug). | `characters` for a language Humanus counts in characters (Chinese), `translated` for every other |

A setting that breaks a rule is refused with a message naming it: a prefix two languages share, a public or slug language the site does not write in, a public list without the primary, an unknown slug policy. The projection reads the setting once per run (one record read).

Only the "primary at root" URL mode exists: the primary language keeps every address it has; each other language lives under its prefix with the same structure (`/es/articles/{slug}/`). The "language prefixed" mode for new sites is not built.

## Editions

The standard front end projects a site that serves more than one language as one edition per public language (`src/papyrus_content/projection/standard/editions.py`). The primary edition is the site as it always was. Every other edition is the same front end over that language's published Stories only, with its pages under `/<prefix>/` and the words of its settings taken from the language's interface strings.

| An edition renders | An edition does not render (their words are the primary's) |
| --- | --- |
| the language's Story pages; its home and section listings, with paging and archives; its RSS and Atom feeds (`/es/feed.xml`); its sitemap (`/es/sitemap-0.xml`) | authored pages, collections, tag pages, the showcase, Reference grids and section front pages, plugin pages, forms, page actions, `llms.txt`, Markdown twins of listings, a 404 of its own |

A language with nothing published has no page, feed or sitemap. A localization is served only while its original is published: its group facts (section, references, stars) are the original's.

So an English listing, feed or sitemap never lists a translation, and a Spanish one lists only Spanish Stories. The static projection needs no new index for this: it already reads every published summary once per run (`list_published_item_summaries`), and each summary carries `language` and `languageGroupId` (copied onto `PublishedItem` at publish; no index on them).

The CMS's own listing keys (`typeStatus`, `sectionStatus`, `headStageKey`, read by the console, the reader app and the newsroom commands) do not carry the language yet; that is the plan's "listing keys carry the language" change, filed as PPY-2be1a0 (see [Not built yet](#not-built-yet)).

## What each page says about its languages

On a site that serves more than one public language:

- `<html lang>` is the page's own language tag.
- The head lists `<link rel="alternate" hreflang>` for each public language the page is published in, itself included, then `x-default` (the primary language's page). A page that exists in one language only lists none.
- `og:locale` is the page's tag with an underscore (`es_419`), with an `og:locale:alternate` for each other language; the article JSON-LD has `inLanguage`.
- Each page is canonical to itself.
- The sitemap index lists one sitemap per language (`sitemap-0.xml`, `es/sitemap-0.xml`); with the `single` style every language's URLs are in the one `sitemap.xml`.

Alternates exist for Story pages (the published members of the language group), the home, and page 1 of each section listing (the editions whose listing at that address exists).

Publishing, renaming or taking down a localization renders the other languages of its group again (their alternates change): as many item pages as the group has languages, in the same projection (`dependent_item_ids` in the projector, `_render_dependents` in the engine), and only those. A listing page's input digest includes its alternates, so the home and section pages of each language are rendered again when a language gains or loses that page.

## What a site's hooks receive

Every `StandardPage` (see `hooks.py`) carries:

| Field | Content |
| --- | --- |
| `page.language` | the page's BCP 47 tag |
| `page.strings` | the site's interface strings in that language (`strings/<tag>.json`) |
| `page.primary_language` | the site's primary language (on a site that serves several) |
| `page.alternates` | `({tag, name, url}, ...)`: the page in every public language it exists in, itself included, primary first; `name` is the language's name in itself (`Español`, `中文`); empty when the page exists in one language |
| `page.link_map` | `{page path: {tag: page path}}` for every Story page and listing that exists in more than one language |
| `page.link_in_language(path)` | `(path, leaves_the_language)`: where a link to a page of this site goes from this page. A page that exists in this page's language is linked there; one that does not keeps its address and `leaves_the_language` is True, so the site marks the link. |

A language switcher draws `page.alternates`; the head tags are core's. The translator never chooses link targets: the published language groups decide them.

## Interface strings

A site's chrome words live in its static directory, one file per language: `strings/en.json`, `strings/es-419.json`, `strings/zh-Hans.json`, each a flat object of `key: text`. The primary language's file names every key the site's own chrome needs; hooks read them from `page.strings`.

A language is public only when its interface strings are complete (`projection/standard/interface_strings.py`). The projection refuses a public language whose file lacks a key it requires, naming the language and the keys. The required keys are every key of the primary language's file plus the ones the standard front end needs, derived from `projection.json`:

- `language.name` (also required in the primary's file);
- `home.label`;
- `listing.pageSuffix` (with `{page}`);
- `site.description` and `site.tagline`, when set;
- `section.<name>.label` and, when set, `section.<name>.description`, for each section with a listing page;
- `nav.<href>.label`, for each navigation link an edition keeps (the home and section listings; other links leave the edition and are dropped);
- `footer.text`, when set.

The strings are part of the shared fingerprint, so changing one renders the site again. The core components' own fixed words (`Skip to main content`, `Menu`, `Newer`, `Older`) are not interface strings yet, so a site whose hooks do not draw its own body and navigation would show them in English on an edition (PPY-ec7c41).

## Unicode addresses

A Chinese localization has a slug in Chinese characters (`能泄露你住在哪里的声音`). One rule covers every address (`src/papyrus_content/url_paths.py`):

- An object key (S3, a local build) is the page's path as text in Unicode NFC: `zh/articles/能泄露你住在哪里的声音/index.html`. A slug is normalised to NFC when it is drafted and when its key is built, so a decomposed spelling is the same page.
- Every URL Papyrus writes is the percent-encoded form of that key (UTF-8, upper-case hex, RFC 3986 path characters left as they are): links, canonical, `og:url`, `hreflang`, sitemap `<loc>`, redirect sources and targets, and edge invalidation paths. A key in ASCII is unchanged by the encoding, so no existing address changes.
- `UrlPolicy.key_for_path` decodes a path back to its NFC key.
- An invalidation path is counted once per form a page is cached under (`/dir/` and `/dir/index.html`), encoded, against the 25-path cap.

A slug's stored form is `page_slug` (`markus_renderer/build.py`): a name whose every character folds to ASCII gets the ASCII slug exactly as before; a name in a script with no ASCII form, already a slug (lowercase letters and digits joined by single hyphens), is kept in NFC.

Drafting a slug (`localized_slug`, used by the translation procedure at a localization's first publish):

- `characters`: full-width letters and digits become ordinary ones and letters are lowercased (NFKC); every run of anything that is not a letter or digit (punctuation, full-width punctuation such as `，。「」`, symbols, spaces including the ideographic space) becomes one hyphen. `AI，会说谎吗？「真相」` becomes `ai-会说谎吗-真相`.
- The longest slug is 384 bytes once percent-encoded (42 Chinese characters), cut at a hyphen or a whole character. A retired page's address becomes a key of the edge's redirect store, a CloudFront KeyValueStore whose keys are at most 512 bytes; 128 bytes are left for the prefix, the section and the slashes.
- A title that leaves nothing (only punctuation) is refused: the localization waits for a person to give it a slug. No address is invented.
- `unique_slug` adds `-2`, `-3` and so on until no other Story of the same language has the slug.
- After the first publish the slug is fixed by the slug lock; a later change is a retire with redirect for that language only.

What the tests prove (synthetic site, fakes): the NFC key in the page writer's store; the encoded canonical, `hreflang`, sitemap entry and listing link; a decomposed slug served at the composed key; a renamed Chinese page redirected from the encoded old address to the encoded new one; encoded invalidation paths, one per cached form.

What only a real CloudFront and S3 can prove (a gated check before any Chinese page is public; no AWS was used to build this):

1. A browser request for the encoded path reaches the S3 object stored under the UTF-8 key, through the edge function's directory-index rewrite.
2. The edge function's redirect lookup matches the encoded request URI exactly (a client that sends raw UTF-8 or lower-case hex would miss the redirect).
3. CloudFront accepts the encoded invalidation paths and purges the cached page.
4. The S3 page writer's `put_object` and `head_object` with a non-ASCII key, and the redirect store's `update_keys` with an encoded key near the 512-byte limit.
5. Search engines and social previews read the encoded canonical and `hreflang` as the same page.

## Not built yet

- The CMS listing keys with the language (`typeStatus`, `sectionStatus`, `headStageKey`), for the console, the reader app and the board: PPY-2be1a0. It needs no new index: the same keys, rewritten by a backfill.
- The language-prefixed URL mode and the countdown banner (PPY-ec591c; Machines on Machines has its own switcher and banner in its hooks).
- Re-rendering the pages that link to a Story when its first translation in their language is published, so their `link_in_language` targets update: PPY-8c11f0. Until then such a page picks up the new target when it is next rendered.
- Interface strings for the core components' fixed words: PPY-ec7c41.
- Per-language search indexes, localized dates and numbers, the AI-translation label and quotation marks (the translation procedure, PPY-bc1a38).
