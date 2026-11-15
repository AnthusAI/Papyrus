# Authored pages in language editions

Status: items 1 and 2 built in the first slice (opt-in `languages: "localize"`, per-language page files, `page.<id>.*` strings, alternates, link map, shared References and threads snapshot); 3 (paged Reference lists in an edition), 4, 5 and translated path segments not built (2026-11-15). Raised by Ryan's goal that a Spanish or Chinese reader can use the whole site in their language. Builds on [docs/multilingual-serving.md](../multilingual-serving.md) (editions) and [multilingual-publishing.md](multilingual-publishing.md).

## Problem

An edition (`/es/`, `/zh/`) renders the language's Story pages, its home and its section and type listings. It renders no authored page (`edition_settings` sets `pages=()`, `collections=()`, `home_page=None`), so on Machines on Machines Findings, Videos, Conversations, About and Corrections exist in the primary language only. Until this plan is built the site's navigation, menu and footer name those pages in the language and link to the English page, marked as leaving the language (MoM `features/language-navigation.feature`). The link is a stand-in: the reader still ends up in English.

## What an edition's authored page is

A page declared in `pages` opts in with `"languages": "localize"` (default `"primary"`, today's behaviour). An opted-in page is rendered once per public language at `/<prefix>/<path>/`, with:

- its title, description and fixed words from the language's strings (`page.<id>.title`, `page.<id>.description`, plus the includes' own words), required for every public language when the page opts in, like `nav.<href>.label`;
- its includes evaluated over the edition: `listing` includes already read the edition's Stories; `references` and `threads` includes read the same Reference and thread records as the primary page (the records are not translated), drawn with the page's chrome in the language;
- authored prose pages (About, Corrections) take their text from a sibling file in the language (`web/pages/about.es-419.md`), written by the translation procedure (extended to authored pages) or by a person; a page with no file in a language is not rendered in it (no fallback), so it is not an alternate and the navigation keeps linking to the primary page;
- `page.alternates`, the link map, `hreflang`, the sitemap and the switcher as for the home: the page in each language it is rendered in, itself included.

## Items whose text is in the source language

Findings and Videos list accepted References: external sources with a title and a generated summary written in the primary language. Conversations lists threads: people's and agents' messages, in whatever language they wrote. These are not translated Stories and are not translated by this plan (translating a source's title or a person's message is a separate decision). An edition's page lists the same items as the primary page, each card's text carries `lang="<language of the text>"` (the primary language unless the record says otherwise), and a one-line notice at the top ("Los elementos de esta página están en el idioma original: inglés.", `edition.originalLanguageNotice` with `{language}`) says so. Card chrome (labels, dates, star counts, "Read the source") is the language's.

## Navigation switch

The site's navigation reads `page.link_map` (MoM `_destination`): a destination that has a localization in the page's language is linked there, otherwise the primary page. So the switch from link-through to the localized page is the page appearing in the link map, with no change to MoM. A page is turned on one language at a time by publishing its strings (and, for prose pages, its file).

## Work and sizes

| # | Change | Size |
| --- | --- | --- |
| 1 | `pages[].languages` setting, validation, required `page.<id>.*` strings per public language (`interface_strings.py`, `config.py`) | S |
| 2 | `edition_settings` keeps opted-in pages; the projector renders them per edition with the edition's strings; alternates, link map, `hreflang`, sitemap, input digest | M |
| 3 | `references` and `threads` includes in an edition: same records, edition chrome and `lang` marks, the original-language notice; the chunk data files under `/<prefix>/reference-lists/` | M |
| 4 | Prose pages: per-language page files, no file means not rendered; the translation procedure for authored pages | M |
| 5 | The edge function serves each language's 404 (`/<prefix>/404.html` for a request under the prefix), and editions render `404.html` and the Markdown twins of their listings | S |
| 6 | MoM: strings for the pages, band and card words; features; nothing in the navigation | S |

Order: 1, 2 (About and Corrections need only 4 on top), 3, then 5. Item 5 also fixes today's loose end that an edition's home advertises `/<prefix>/index.md`, which is not rendered.

## Decided (2026-11-15)

Source-language items appear in localized listings marked `lang` with the one-line notice; Conversations are localized the same way; About publishes when its translation is clean and Corrections is always held for a person; pages launch at their final, translated addresses (a per-language slug table for section, type and page path segments, with 301 redirects from the English segments under each prefix), so item 6 below precedes turning any page on.

| # | Change | Size |
| --- | --- | --- |
| 7 | Translated path segments: a per-language slug table (settings, validated: unique, URL-safe once percent-encoded, no collision with Story slugs), used by listings, authored pages, nav, sitemap, hreflang, canonical, switcher, feeds and twins; 301 redirects from the English segments | L |

## Decisions (original questions, now answered)

1. Source-language items in a localized listing marked with `lang` and a notice (this plan), or the listing left in English only.
2. Whether Conversations (people's own words) should be localized at all, or stay English-only with the localized shell linking through.
3. Who writes About and Corrections in Spanish and Chinese: the translation procedure extended to pages, or a person.
