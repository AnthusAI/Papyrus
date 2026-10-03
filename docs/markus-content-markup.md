# Markus content markup: responsive images and inline citations

Two capabilities that the Markus renderer (`src/papyrus_content/markus_renderer/`)
gained so a real blog can be published through it: **build-time responsive
images** and **inline citations with an end-of-article bibliography**.

This document is the **authoring contract**. Reader-site build scripts and
content codemods are written against the syntax specified here; if the syntax
changes, this file changes first.

- Module: `src/papyrus_content/markus_renderer/{images,citations,content_markup}.py`
- Tests: `procedures/newsroom/tests/test_markus_content_markup.py`
- First client: the Anth.us port (`publications/anth_us/`), ported from
  `BlogImage` (234 uses), `Citation` (201 uses) and `CitationsList` (25 uses)
  in `AnthusAI/anthus-site-content`.

## TL;DR for a codemod

| Gatsby MDX | Papyrus Markdown |
| --- | --- |
| `<BlogImage images={…} name="chart.png" className="full" alt="A chart" />` | `::image{src="images/chart.png" layout="full" alt="A chart"}` |
| `<Citation data={{type: "webpage", title: "…", URL: "…"}} />` | front-matter `citations:` entry + `[@key]` at the point of use |
| `<CitationsList citationFormat="apa" />` | `::citations{format="apa"}` |

## Both capabilities are opt-in

```python
from papyrus_content.markus_renderer import (
    CitationRendering, ImagePipeline, build_markus_site,
)

build_markus_site(
    content_dir=pod / "content",
    out_dir=pod / "dist",
    images=ImagePipeline(),          # responsive images + ::image{}
    citations=CitationRendering(),   # [@key] + ::citations{}
)
```

With `images=None` and `citations=None` — the defaults — `build_markus_site`
does not inspect or rewrite a single fragment. That is a hard requirement, not
a nicety: Pilobol.us builds against this module in production and must keep
getting byte-identical output. `BuildIntegrationTests.test_default_build_is_untouched_by_the_new_capabilities`
pins it.

Consequence worth knowing: `::image{}` is **Papyrus** markup, not Markus
markup. If content uses it and the build script forgot `images=…`, Markus sees
an unregistered directive and fails with
`Unknown directive 'image'`. That is deliberate — a loud failure beats
silently dropping every image.

## Why this syntax

The honest constraint. Markus owns the Markdown vocabulary and validates it
strictly:

- directive attribute schemas are pydantic models with `extra="forbid"`, so
  `:::figure{…}` physically cannot carry a `layout` or a `sizes` hint;
- an unregistered directive name is a hard validation error;
- `convert_fragment` shells out to the **pinned `markus` CLI** (0.5.1), which
  is also the security boundary — the build never passes `--allow-html`, so
  authors can never introduce raw HTML. Registering a directive in-process
  would mean giving that up.

Three options were on the table.

1. **Attribute suffixes** (`![alt](src){.full}`, Pandoc / `markdown-it-attrs`
   style). Rejected after testing it: Markus emits the braces as literal text
   (`<p><img …/>{.full}</p>`). Not supported, and faking it would mean
   string-surgery on rendered HTML to find and remove author-visible debris.
2. **Patch Markus to register new directives.** Rejected for this work: it
   moves the change into a different repo and out of the pinned-CLI security
   model, and it blocks the port on a Markus release.
3. **A thin Papyrus layer, resolved before Markus runs.** Chosen. Papyrus
   lowers its own constructs to opaque alphanumeric sentinels, lets Markus
   convert the Markdown it does own, then substitutes real HTML into the
   fragment. Markus never sees Papyrus markup; Papyrus never has to parse
   Markdown.

Spelling follows Markus's own grammar on purpose (`::name{…}` for a
leaf/block-level construct) so authors keep one mental model, and `[@key]` is
Pandoc's long-established citation spelling. Neither is a Markus directive.

Security is unchanged by the layer: a sentinel carries no content, every
attribute is HTML-escaped at substitution time, and image `src` values are
validated (`javascript:`, `data:`, absolute paths and `..` traversal are all
rejected).

Papyrus markup inside a fenced block or an inline code span is **not**
lowered, so a document can document the syntax — including this one.

## Images

### `::image{…}`

On a line of its own:

```markdown
::image{src="images/price-of-fixed-capability.png" layout="full" alt="Log-scale chart of the cost to reach a fixed benchmark score."}
```

| Attribute | Required | Meaning |
| --- | --- | --- |
| `src` | yes | Path relative to the pipeline's `source_dir` (defaults to the build's `content_dir`). An `http(s)://` URL is emitted untouched. |
| `alt` | — | Alt text. Use `alt=""` for decoration. |
| `layout` | — | Named layout; drives the CSS class and the `sizes` attribute. Defaults to `inline`. |
| `caption` | — | Renders a `<figcaption>`. |
| `credit` | — | Appended to the caption in `<span class="papyrus-image-credit">`. |
| `sizes` | — | Override the layout's `sizes` for this one image. |
| `loading` | — | `lazy` (default) or `eager`. `eager` also sets `fetchpriority="high"`. |

Any other attribute is a build error that names the offender.

Quoting: `key="value"`, `key='value'` and bare `key=value` all parse. Use
quotes for anything containing a space.

The attribute block may wrap across lines, which is what a codemod lifting a
multi-line JSX element produces anyway, and is more readable for a long `alt`:

```markdown
::image{
  src="images/price-of-fixed-capability.png"
  layout="full"
  alt="Log-scale chart of the cost to reach a fixed benchmark score from 2023
  to 2026, falling roughly five to ten times per year."
}
```

The closing `}` must end its own line. An attribute value containing a literal
`}` is not supported. Whitespace in `alt`, `caption` and `credit` is collapsed
to single spaces, so wrapping does not leak newlines into the HTML attribute.

### Plain Markdown images are upgraded too

`![alt](images/chart.png)` and `:::figure{src="images/chart.png"}` get the
same renditions, `srcset`, `sizes` and intrinsic dimensions, so authors do not
*have* to reach for `::image{}` — they reach for it when they want a layout, a
caption or a credit. Positioning is respected:

| Source | Output |
| --- | --- |
| Markdown image alone in its paragraph | wrapped in `<figure class="papyrus-image …">` |
| Markdown image inside a sentence | replaced in place, no `<figure>` |
| `:::figure{src=…}` | Markus's own `<figure class="markus-figure">` is preserved; only the `<img>` is upgraded |

Turn this off with `ImagePipeline(upgrade_plain_images=False)` if a
publication wants `::image{}` to be the only responsive path.

### What gets emitted

```html
<figure class="papyrus-image papyrus-image--full">
  <picture>
    <source type="image/webp"
            srcset="../assets/responsive/images/chart-480.webp 480w, … 1920w"
            sizes="(max-width: 48rem) 100vw, 48rem">
    <img src="../assets/responsive/images/chart-1024.png"
         srcset="../assets/responsive/images/chart-480.png 480w, … 1920w"
         sizes="(max-width: 48rem) 100vw, 48rem"
         alt="…" width="2400" height="1350" loading="lazy" decoding="async">
  </picture>
  <figcaption>Falling cost · <span class="papyrus-image-credit">Anthus</span></figcaption>
</figure>
```

- `width`/`height` are the **source's intrinsic** pixel dimensions, which is
  what lets the browser reserve the right aspect box and avoid layout shift.
- Asset URLs are prefixed for page depth (`../`) the same way
  `shell.render_page` prefixes stylesheets and nav links.
- The original format is always among the renditions so the `<img>` fallback
  works without `<picture>` support.
- `.svg` and `.gif` are **never** re-encoded or resized: they are copied
  verbatim and emitted as a single `<img>`, with intrinsic dimensions when
  they can be read (SVG `width`/`height` or `viewBox`). This matches the
  `publicURL` fallback `BlogImage` used for those types.
- Renditions are never upscaled past the source width.

### Pipeline configuration

`ImagePipeline` (frozen dataclass) — the publication-level knobs:

| Field | Default | Notes |
| --- | --- | --- |
| `source_dir` | the build's `content_dir` | Where `src` resolves from. |
| `cache_dir` | `<content_dir>/.papyrus-image-cache` | See below. |
| `out_subdir` | `assets/responsive` | Where derivatives land in the built site. |
| `widths` | `(480, 768, 1024, 1366, 1920)` | Plus the source's own width. |
| `max_width` | `None` | Ceiling on the widest rendition. |
| `formats` | `("webp",)` | Offered via `<source>`; the source format is always emitted as the fallback. `avif` is dropped silently when the installed Pillow cannot encode it. |
| `quality` | `82` | |
| `fallback_width` | `1024` | Which rendition the `<img src>` points at. |
| `layout_sizes` | `DEFAULT_LAYOUT_SIZES` | Layout name → `sizes`. An unknown layout is a build error listing the known ones. |
| `default_layout` | `inline` | |
| `figure_class` / `layout_class_template` | `papyrus-image` / `papyrus-image--{layout}` | |
| `emit_layout_class_verbatim` | `False` | Also emit the bare layout word as a class. A porting affordance — see below. |
| `default_loading` | `lazy` | |
| `upgrade_plain_images` | `True` | |
| `strict` | `True` | A missing file fails the build. `False` leaves the original `<img>` alone. |

Add or override layouts without retyping the table:

```python
from papyrus_content.markus_renderer import ImagePipeline, with_layouts

pipeline = with_layouts(
    ImagePipeline(emit_layout_class_verbatim=True),
    {"hero": "100vw"},
)
```

**`emit_layout_class_verbatim`.** A site being ported already has CSS keyed on
its own class names (`.gatsby-image-wrapper.full`, `.centered`, `.right`).
Turning this on emits `class="papyrus-image papyrus-image--full full"` so that
stylesheet keeps working during the port. It is off by default because
framework output should not depend on a publication's vocabulary.

**`cache_dir` matters.** `build_markus_site` wipes its output directory on
every run, so derivatives are generated into a cache *outside* that tree and
copied in. Without it, every build would re-encode every rendition of every
image — for a 234-image corpus at five widths and two formats that is
thousands of encodes per deploy. Put `cache_dir` on the CI cache path (or
commit it) to make rebuilds cheap.

**Known limitation.** Derivative filenames are `<stem>-<width>.<ext>`, not
content-hashed. Replacing an image file with different bytes at the same path
and the same dimensions keeps the same URL, so a CDN or browser can serve the
old bytes. Rename the file to bust it. (Regeneration itself is correct —
derivatives are rebuilt whenever the source is newer.)

### Requirements

Pillow. It is imported lazily, only when a pipeline is configured, so
publications that have not opted in do not need it. Verified against Pillow
10.3.0 (webp yes, avif no).

## Citations

### Data lives in front matter

```yaml
---
title: The cost of a fixed capability keeps collapsing
citations:
  gundlach-2025-price-of-progress:
    type: article-journal
    title: "The Price of Progress: Price Performance and the Future of AI"
    author: ["Hans Gundlach", "Jayson Lynch", "Matthias Mertens", "Neil Thompson"]
    container-title: arXiv
    DOI: 10.48550/arXiv.2511.23455
    URL: https://arxiv.org/abs/2511.23455
    issued: {date-parts: [[2025, 11]]}
    accessed: {date-parts: [[2026, 8, 16]]}
  openai-codex-long-horizon:
    type: webpage
    title: Run long horizon tasks with Codex
    container-title: OpenAI Developers
    URL: https://developers.openai.com/blog/run-long-horizon-tasks-with-codex
    accessed: {date-parts: [[2026, 8, 16]]}
---
```

`citations:` is a mapping of **key → CSL-JSON object**. CSL-JSON is the same
shape `<Citation data={…}>` already carried, so a codemod is a hoist plus a
key, not a schema translation. It is also the interchange format Papyrus's
newsroom reference machinery already speaks.

Keys are author-chosen and must be unique within the page. `author` accepts
plain strings (`"Hans Gundlach"`), CSL name objects (`{family, given}`), and
`{literal: "OpenAI"}`.

### Reference a citation in prose

```markdown
Cost per unit of capability keeps falling [@gundlach-2025-price-of-progress],
and agents now run for hours at a stretch [@openai-codex-long-horizon].
```

Several in one bracket, semicolon-separated:

```markdown
Both lines of work agree [@gundlach-2025-price-of-progress; @openai-codex-long-horizon].
```

Renders, per reference:

```html
<span class="citation"><a href="#citation-1">1</a></span>
```

An unknown key fails the build and lists the page's known keys
(`CitationRendering(strict=False)` leaves the raw `[@key]` text in place
instead).

### The bibliography

```markdown
::citations{format="apa"}
```

`format` is optional and defaults to `CitationRendering.default_format`
(`apa`). Renders:

```html
<ol class="citationslist">
  <li id="citation-1">Gundlach, H., Lynch, J., Mertens, M., &amp; Thompson, N. (2025, November). The Price of Progress… arXiv. <a href="https://arxiv.org/abs/2511.23455" target="_blank" rel="noopener noreferrer">https://arxiv.org/abs/2511.23455</a></li>
</ol>
```

Omit `::citations{}` and no list is rendered — the inline markers still get
numbers, they just link to anchors that are not on the page. That matches what
the Gatsby site did for the one article with no `<CitationsList>`.

### Numbering rules

- Numbers follow **order of first appearance** in the rendered page.
- Repeating a key reuses its number.
- The list contains exactly one entry per **cited** key, in the same order.
  Declared-but-uncited entries are omitted.

This last point is a deliberate **divergence** from
`gatsby-citation-manager`, which numbered by first matching `title` but
appended every `<Citation>` to the list. Two entries sharing a title (which
happens in the Anthus corpus — same paper, two URLs) therefore produced a list
item nothing linked to and an inline marker pointing at the other one. Keying
on an explicit key removes the failure mode.

### CSS contract

The renderer emits structure, not style. A reader stylesheet needs, at
minimum, the bracket rule the markup relies on:

```css
.citation { display: inline; vertical-align: baseline; font-size: 0.75em; }
.citation::before { content: "["; }
.citation::after  { content: "]"; }
.citation a { text-decoration: none; color: inherit; }
.citationslist { text-align: left; word-break: break-word; }
.citationslist li { margin-bottom: 1.5rem; }
```

The brackets are CSS rather than markup because that is where the ported site
put them, and because it keeps the number the only text in the DOM — a
selection or a screen reader is not fighting punctuation.

### Formatting

`format_apa` is a dependency-free APA-7-shaped formatter covering the ten CSL
`type` values and seventeen fields that actually occur in the corpus being
ported. Output is **plain text**, because the component it replaces also
produced plain text: it read `.csl-entry` `textContent`, discarding citeproc's
italics.

It is an approximation, not a CSL processor. It was run across all 201 CSL
objects extracted from the live Anthus corpus (201/201 formatted without
error), but it will not be byte-identical to `citation-js` output in every
case. If exact citeproc fidelity is ever required, inject a real processor:

```python
CitationRendering(formatters={"apa": my_citeproc_formatter})
```

Unknown format names are a build error that lists the known ones.

### Configuration

| Field | Default |
| --- | --- |
| `default_format` | `apa` |
| `marker_class` | `citation` |
| `list_class` | `citationslist` |
| `anchor_prefix` | `citation-` |
| `formatters` | `{}` (merged over the built-ins) |
| `strict` | `True` |

## Why not build on Papyrus's existing reference machinery

`reference_citation_resolution.py`, `reference_discovery.py` and
`references_commands.py` are the newsroom **knowledge-base** side: they take
curated `Reference` records out of GraphQL, query Crossref and OpenAlex to
attach a DOI/arXiv identifier, and write a `citationResolution` block back onto
the record. Nothing there produces HTML, formats a bibliography entry, or has
any notion of a position in a sentence. It operates on records whose
`externalItemId` starts with `citation:` — a KB identity, not a footnote
marker. See `docs/reference-processing-terminology.md`.

A reader needs the other half, and needs it to work from repo-committed
Markdown inside a static build with no GraphQL round trip. So this is built
alongside that machinery, not on top of it. The deliberate bridge is the data
format: entries here are CSL-JSON, which is what the KB code already resolves
identifiers against, so a later change can populate a page's `citations:`
block from curated references without touching the renderer.

## Full example

````markdown
---
title: Same coding capability, falling price
citations:
  gundlach-2025-price-of-progress:
    type: article-journal
    title: "The Price of Progress: Price Performance and the Future of AI"
    author: ["Hans Gundlach", "Jayson Lynch", "Matthias Mertens", "Neil Thompson"]
    container-title: arXiv
    URL: https://arxiv.org/abs/2511.23455
    issued: {date-parts: [[2025, 11]]}
---

# Same coding capability, falling price

The price of a fixed benchmark score has fallen five to ten times a year
[@gundlach-2025-price-of-progress].

::image{src="images/price-of-fixed-capability.png" layout="full" alt="Log-scale chart of the cost to reach a fixed benchmark score from 2023 to 2026."}

A plain Markdown image gets the same treatment, minus the layout and caption:

![An agent at a control panel](images/ai-agent-at-control-panel.png)

Markup inside code is left alone, so this renders literally:
`::image{src="x.png"}`, `[@gundlach-2025-price-of-progress]`.

## Citations

::citations{format="apa"}
````
