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

## File names and URL slugs

Any `*.md` in `articles/` (or another section directory) is a page. Its URL
slug is derived from the file name by `markus_renderer.build.slugify`:
ASCII-fold, lowercase, every run of non-alphanumerics (spaces, underscores,
punctuation) becomes a single hyphen, leading/trailing hyphens stripped. So
`Paytronix.md` is served at `articles/paytronix.html` and `Call Criteria.md`
at `articles/call-criteria.html`; an already-lowercase name is unchanged.
Names starting with `_` or `.` are not pages. The build fails if two files
derive the same slug (both are named) or a name leaves no slug at all.

## On by default for a site, opt-in for the library

A Papyrus **site** (a `projection.json`, or none) has both capabilities without declaring them. Set `"images": false` or
`"citations": false` to turn one off; declare `"images"` as an object (`widths`, `formats`, `layouts`, ...) to configure the
pipeline. Without a declaration the pipeline's own defaults apply, `::image` is rendered from the renditions made when the
picture is uploaded, and plain Markdown images are left as written (declaring `images` as an object also upgrades them). A
site with no media bucket cannot show a picture: `::image` is refused at save, with that reason.

Save and publish read the same site settings: a body the page cannot be made from (`::image` on a site that turned images off,
a citation key that does not exist, a picture whose renditions were never made) is refused when it is saved or published,
before any published data is written. See `docs/standard-site.md`, "Images and citations".

The rest of this section is the library call, `build_markus_site`, where both are opt-in.

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
- `convert_fragment` shells out to the **pinned `markus` CLI** (0.7.0), which
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
| `srcDark` | — | The dark-mode picture of `src`. See [Light and dark pictures](#light-and-dark-pictures). `srcDark="none"` turns off name pairing for this one image. |

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

### Light and dark pictures

A figure can carry a second picture for dark mode:

```markdown
::image{src="images/botspy-1.png" srcDark="images/botspy-1.dark.png" alt="…"}
```

You can leave `srcDark` out. When `images/botspy-1.dark.png` exists next to
`images/botspy-1.png` (the name with `.dark` before the extension; any image
extension), an `::image{}` pairs them automatically. `srcDark` is the explicit
override for any other file name.

- **Same pipeline.** The dark file gets its own widths, WebP/AVIF renditions and
  intrinsic size, exactly like the light one. An `.svg` or `.gif` dark file is
  passed through, like any `.svg` or `.gif` (vector and animated files are never
  re-encoded).
- **Same proportions.** The light file's `width` and `height` size the figure.
  The dark file must have the same aspect ratio (within 0.5%, which absorbs a
  one-pixel rounding difference), or the build fails and names the image, so a
  theme switch never moves the page. A missing dark file, or a `srcDark` that is
  a URL, is a build error too.
- **Markup.** Both pictures are in the page, each in its own wrapper:
  `<div class="papyrus-image-light">` and `<div class="papyrus-image-dark">`
  (`<span>` for an inline image). The dark one is always `loading="lazy"` and
  hidden with `display:none`, so a browser does not download the picture that is
  not showing. A `<source media="(prefers-color-scheme: dark)">` cannot see a
  site's theme toggle, which is why the swap is done with CSS on the wrappers.
- **The theme hook.** The first figure on a page emits a small `<style>` block
  (`DARK_VARIANT_CSS`). It follows the **site's theme setting** first:
  `data-theme="dark"` or `data-theme="light"` on the root element (`<html>`)
  decides, whatever the operating system prefers. A site whose toggle sets a
  `dark` class on the root (and no `data-theme`) works too. With neither set,
  the reader's `prefers-color-scheme` decides. **A site's toggle only has to set
  `data-theme` on `<html>`.** There is no per-site code or configuration. Set it
  as early as possible (a script in `<head>`) so the hidden picture is never
  fetched.
- **Plain Markdown cannot express a pair**, so `![alt](…)` and `:::figure{src=…}`
  never get a dark picture, even when a `.dark` file exists. Use `::image{}`.
- **Feeds and other readers** that ignore CSS show both pictures.

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
| `formats` | `("webp",)`; `("avif", "webp")` with `gatsby_parity` | Offered via `<source>`; the source format is always emitted as the fallback (JPEG/PNG under `gatsby_parity`). A listed format the installed Pillow cannot encode is a **build error**, not a silent drop. |
| `quality` | `82`; `70` with `gatsby_parity` | |
| `gatsby_parity` | `False` | Clone gatsby-plugin-image; see below. |
| `placeholder` | `"blurred"` | `gatsby_parity` only: `"blurred"` or `None`. |
| `eager_first` | `2` | `gatsby_parity` only: images per page that load eagerly. |
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

### `gatsby_parity=True`: gatsby-plugin-image behaviour

One switch for publications ported from Gatsby. Off (the default) nothing
above changes. On, as gatsby-plugin-image's `constrained` layout does it:

- **Breakpoints.** The display width is the source's width (capped by
  `max_width`); renditions are 0.25x, 0.5x, 1x and 2x of it, dropping any wider
  than the source (`gatsby_widths`). A 2048px source gets 512/1024/2048 with
  `sizes="(min-width: 2048px) 2048px, 100vw"`. `widths`, `fallback_width` and
  `layout_sizes` are not used; a per-image `sizes` still wins.
- **Formats.** AVIF, WebP, then the fallback `<img>`. The fallback is JPEG for
  an opaque image and PNG only when a pixel is really transparent. (Gatsby's
  `"auto"` keeps the source format, so it ships photographic PNGs as PNG; that
  fallback is only fetched by browsers with neither AVIF nor WebP.)
  Quality 70, progressive JPEG.
- **Placeholder.** A 20px-wide inline `data:` image (gatsby's `blurred`),
  faded out when the real image has decoded. `placeholder=None` reserves the
  box and shows nothing, which is what anth.us's article images do.
- **Aspect-ratio box.** The default `<figure>` wraps the `<picture>` in
  `<div class="papyrus-image-frame" style="max-width:Wpx;aspect-ratio:W / H">`.
  The first image on a page also emits the frame CSS, a `<noscript>` override
  and `FADE_IN_SCRIPT` (gatsby's fade-in, ported). No JavaScript: images show.
- **Eager loading.** The first `eager_first` images on each page are
  `loading="eager" fetchpriority="high"`; the rest use `default_loading`.

With a `wrap` hook, Papyrus emits none of the frame or support block: the hook
owns the DOM. `ImageWrap.placeholder` carries the data URI, the main `<img>`
has `data-main-image=""`, and the publication includes `FADE_IN_SCRIPT` once
per page (it understands `data-gatsby-image-wrapper` too).

`ImageBuilder.start_page()` resets the per-page eager count and support block;
`render_fragment` calls it before each page.

### Requirements

Pillow. It is imported lazily, only when a pipeline is configured, so
publications that have not opted in do not need it. WebP works on Pillow 10.3;
**AVIF needs Pillow >= 11.3**, whose wheels bundle libavif on macOS and Linux
(`pip install "Pillow>=11.3,<12"`). Configuring `avif` on an older Pillow
raises `ImagePipelineError`.

## Videos

### `::video{…}`

A video is written like an image, on a line of its own:

```
::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft sound localisation demonstration" caption="Two microphones, one jet." credit="Example Channel" start="90"}
```

| Attribute | Required | Meaning |
|-----------|----------|---------|
| `src` | yes | The address of the video. YouTube (`watch?v=`, `youtu.be`, `shorts`, `live`, `embed`), Vimeo (`vimeo.com/ID`, `player.vimeo.com/video/ID`) and Instagram (`/p/`, `/reel/`, `/tv/`) are known. |
| `title` | yes | The player's accessible name (the button and the frame are named by it). |
| `credit` | yes | Who made the video. Third-party media is always credited; the credit links to the video. |
| `caption` | no | What the reader will see before pressing play. |
| `start` | no | Whole seconds to start from. Refused for a provider that cannot start part way (Instagram). |
| `layout` | no | `inline` (default) or `full`, the same classes as `::image`. |
| `poster` | no | A picture in the site's own storage (`/assets/reel-poster.jpg`) to show before the click. Needed for a provider with no thumbnail to copy (Instagram); optional for the others. |

**Click to play.** The page holds a poster (our own copy, read from the site's storage like any picture), a real `<button>` named by the title, and a plain
link to the video for readers without JavaScript. Nothing in the static page asks the provider for anything. Only a click, Enter or Space puts the provider's
player in the poster's place (`_plugins/papyrus-video-v1.js`, which creates a frame only for a registered provider's player address). There is deliberately no
autoplay-on-load and no `clickToPlay` setting.

**Posters.** For a provider with a thumbnail (YouTube, Vimeo) the poster is `assets/video-posters/<provider>-<id>.jpg` in the site's media storage, copied by
`papyrus stories capture-video-posters --story <lineage>` (run where the provider answers, signed in with `papyrus login`; it skips a video that names its own
`poster=`, and tells you which videos need one). A video whose poster is missing shows a flat placeholder with its title, never a broken image and never an address
on the provider. The site needs `"media": {"originals": true}` so the renditions function makes the poster's sizes.

**The provider registry is data** (`markus_renderer/video.py`, `REGISTRY`): for each provider, its hosts and address shapes, the plain address, the player
address, whether a thumbnail can be copied, and the origin the Content-Security-Policy must allow. Adding a provider is adding a row.

**Which providers play** is a setting of the site, `embeds.providers` in `projection.json` (see [the standard front end](standard-site.md#video-embeds-embeds)):

* No `embeds`, or an empty `providers` list (the default): the feature is **absent**. Core does not read `::video` at all, so a site's own hooks see the line exactly as before,
  the site publishes exactly the files it did, and a Story saves with no list of videos.
* A provider listed: its `::video` plays as above.
* Another registered provider that the site does not list, while some provider is listed: a plain linked credit line, `Video: <title linked to the video>. <caption>. Credit: <credit>.`,
  with no player, no picture and no script.
* An address of a host that is not in the registry is never core's: the line is left for the site's hooks.

The Markdown copy of the Story keeps the directive exactly as written.

**Checks.** The four-lens review has P16 (title and credit, a problem that blocks), P17 (caption), P18 (the site lists the video's provider, and an Instagram video has a poster) and A15 (a credited video is among the Story's citations).

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

Keys are author-chosen and must be unique within the page. `author` and
`editor` take either:

- a **list** whose items are `"Given Family"` strings, CSL name objects
  (`{family, given}`), or `{literal: "OpenAI"}`, formatted as APA names
  (`Gundlach, H., Lynch, J.`), exactly as the live site does; or
- a **string**, which is split into people on ` and `, ` & ` and `;` (never on
  commas, so `Smith, J.` is one person) and each is printed as written, as a
  literal name (`Dan Milmo, Ryan Porter`). This deliberately diverges from the
  live site, whose citation-js silently drops a string author. Literal names are
  not inverted or initialised; write a list of names if you want APA inversion.

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
  <li id="citation-1">Gundlach, H., Lynch, J., Mertens, M., &amp; Thompson, N. (2025). The Price of Progress… arXiv. https://doi.org/10.48550/arXiv.2511.23455<a href="https://arxiv.org/abs/2511.23455" target="_blank" rel="noopener noreferrer">https://arxiv.org/abs/2511.23455</a></li>
</ol>
```

Omit `::citations{}` and Papyrus **appends the bibliography at the end of the
article** (inside the `<article>`, formatted as `::citations` would be), so a
marker never links to an anchor that is not on the page (PPY-21bb36). The Gatsby
site left such markers pointing nowhere; that parity is deliberately dropped. A
body with no `[@key]` marker gets no list. The Story checklist's citation check
(A5 in [four-lens-review.md](four-lens-review.md)) tells the editor before
publishing, in plain words, which markers have no `::citations{}` line and which
keys are not among the Story's entries.

### How the bibliography links a source

A publication chooses in `web/projection.json`:

```json
{ "citations": { "links": "internal" } }
```

`citations` is `true` / `false` (as before: `false` turns citations off) or an
object with one key, `links`:

| `links` | Bibliography entry |
| --- | --- |
| `external` (default; also what `true` or no setting gives) | The formatted entry plus the source's own URL as a link, exactly as above. Output is byte-identical to before. |
| `internal` | No outside address, linked or printed. An entry is linked only to the site's own page for it when its CSL-JSON carries `internalUrl` (a path starting with `/` on this site), otherwise it is plain text. |
| `none` | Plain text: title, publisher and date. No link of any kind in the list. |

`URL` and `DOI` are left out of the entry text for `internal` and `none`. An
`internalUrl` that is an address (`https://...`, `//...`, `javascript:`) is never
linked. The inline markers link to `#citation-N` on the same page in every mode,
which is not an outbound link. Today the engine publishes no page per Reference,
so no entry carries `internalUrl` yet and `internal` renders plain text until a
site's Stories add one. Machines on Machines sets `internal`.

### Formatting

Entries are formatted by [citeproc-py](https://pypi.org/project/citeproc-py/)
(a runtime dependency; imported only when a bibliography is rendered) driven by
the **same APA 7 CSL file** the live site's `citation-js` bundles, copied into
`markus_renderer/csl/apa.csl` with its CC BY-SA 3.0 notice (see
`csl/README.md`). The output is plain text, as live: citation-js read the
entry's `textContent`, which dropped the italics. Each entry is formatted on
its own, as live did, so there is no cross-entry sorting or year suffixing.

Three behaviours of the live pipeline are reproduced on top of citeproc-py
because it does not do them itself (all in `citations.py`, each with a test):

- **Title case.** citeproc-js splits at `. , - / : ( )` and capitalises each
  piece, so `Data.gov` renders `Data.Gov` and `X (formerly Twitter)` renders
  `X (Formerly Twitter)`. citeproc-py leaves both alone.
- **Substituted macros.** With no author, APA puts the title first;
  citeproc-py then prints it a second time. A small patch suppresses variables
  rendered inside `<substitute>`, as the CSL spec says.
- **Typography.** Straight `'` and `"` become `’` and `“ ”`, a `.`/`,` after a
  closing quote moves inside it, and no `.` follows `?` or `!`. This covers the
  quote handling the corpus exercises, not every citeproc-js case.

The list item is `formatted text` with the first occurrence of `URL` cut out,
followed immediately by `<a href=URL …>URL</a>`. When the text contains a DOI
URL that differs from `URL`, nothing is cut and the link touches the DOI, as
live. Verified: all 197 entries across the 25 Anth.us bibliographies are
identical to the live site's hydrated DOM except one whose source
`container-title` has a leading space (live keeps a double space that HTML
collapses; citeproc-py trims it).

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
on an explicit key removes the failure mode. Three Anth.us pages differ from
live in marker numbers for exactly this reason, and four have fewer list items
than live (duplicated uses of one source).

A second deliberate divergence: the static HTML live serves (what a crawler or
a no-JavaScript reader gets) has **every marker numbered `0` and an empty
`<ol class="citationslist"></ol>`**, because the list is filled by React after
hydration. Markus renders the final numbered markers and the full list at build
time. "Matching live" means matching the DOM a browser shows after hydration.

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

## Equations

Equations are written as TeX, inside Markdown that Markus already understands, and drawn as MathML when the page is built.
Nothing runs in the reader's browser: no script, no web font, no KaTeX or MathJax. Implementation:
`src/papyrus_content/markus_renderer/equations.py` (converter: [`latex2mathml`](https://pypi.org/project/latex2mathml/), MIT, pure Python).
Tests: `procedures/newsroom/tests/test_markus_equations.py`, `features_backend/story-math.feature`.

| Form | Write | Becomes |
| --- | --- | --- |
| Display | a fenced block whose info string is `math` | `<div class="papyrus-math"><math display="block">`... |
| Inline | a code span with a dollar sign on each side: ``$`m / 2^k`$`` | `<math display="inline">` inside the sentence |

````markdown
The attacker's chance of guessing a $`k`$-bit key in one try is at most $`m / 2^k`$.

```math
H_\infty(X) = -\log_2 \max_x \Pr[X = x]
```
````

Why this spelling:

- **A bare `$` is never math.** Stored articles contain prices ("$5 or $6"), so the dollar sign alone cannot open an equation.
  Only a code span with a `$` directly on each side counts, and `` `$HOME` `` or `` $5 `flat` $6 `` are left alone.
- **The code span protects the TeX.** Markdown reads `_`, `*`, `\` and `{}` in running text, so `a_i * b_j` outside a code span
  loses characters to emphasis and escaping. Inside a code span nothing needs escaping except a literal backtick.
- **It is already portable.** `` ```math `` and ``$`...`$`` are the spellings GitHub and GitLab render, so the Markdown twin, `llms.txt`
  readers and a repository view all show the same equation.
- **Markus is unchanged.** It sees an ordinary fenced block and an ordinary code span (the stored `bodyIr` keeps them, with
  `lang: "math"` on the block). Papyrus swaps them for MathML after Markus has converted the page, the way Mermaid fences are handled.

What is supported is what `latex2mathml` supports: fractions, roots, sub- and superscripts, sums and limits, Greek letters,
`\text{...}`, `\left`/`\right`, matrices, `cases`, and `align`/`aligned` (`aligned` is mapped to the unnumbered `align*`). Known gaps: a
`\mathrm{d}` is a plain letter (the browser may set it in italic), and a `<` or `&` inside `\text{...}` is not supported: that
equation falls back to its source (put the symbol outside `\text`).

### When the TeX is wrong

A page never breaks and never loses text. An equation that cannot be converted keeps the author's source, shown as code
(`<pre><code class="language-math">` or `$<code>...</code>$`). Saving the Story still succeeds, but `derive_body` returns a
non-blocking **warning** with code `equation-tex`, the line number and the reason; `papyrus content markus-derive` prints it under
`warnings`, and the publish path logs it.

### Safety

`latex2mathml` does not escape what an author types: `\text{</mtext><script>...}` would become a real `<script>` element and
`\href{javascript:...}` or `\style{...}` would become attributes. Its output is therefore never trusted. It is parsed, every
element and attribute is checked against a MathML whitelist (no `href`, `style`, `on*`, no `mathcolor`), and the markup is written out
again with every text and value escaped. An equation that fails is shown as source, as above. The renderer also rejects unknown
commands (`\notacommand`) instead of printing the backslash.

### Output contract

- `<math xmlns=... display="block|inline" alttext="TeX source">`. `alttext` is the accessible fallback for assistive technology
  that does not read MathML.
- Display equations sit in `<div class="papyrus-math">` (scrolls sideways instead of overflowing a narrow screen).
- Colour is inherited (`currentColor`), so light and dark themes both work; there are no rules or borders. The CSS lives in
  `markus-components.css`.
- **Math font.** `math { font-family: "STIX Two Math", "Cambria Math", "Latin Modern Math", "Libertinus Math", "Noto Sans Math", "Asana Math", math }`.
  No font is shipped. The generic `math` family alone can resolve to a text font with no OpenType MATH table (seen in Chromium on macOS):
  the display sum sign then stays text-sized with its limits touching it, and `\mid` shrinks. With a real math font the same page
  gets a 24 px sum sign and 5 px / 4 px gaps to its limits. A reader whose system has none of the listed fonts falls back to `math`
  and sees the tighter layout; the equation is still correct and readable.
- **Named operators.** `Pr`, `max`, `lim` (an `<mo>` in the converter's output) get `lspace="0em" rspace="0.1667em"`, and
  `log`/`sin` (an `<mi>`) get a thin `<mspace>` after them, so `\Pr[X]` and `\log_2 \max_x` read as words, not as infix signs.

### Other places an equation appears

| Place | Shows |
| --- | --- |
| Markdown twin (`index.md`), `llms-full.txt` | the TeX source, verbatim (they are built from the source, not the HTML) |
| Newsletter email | the TeX source in code styling (`render_fragment_text(..., equations="source")`); Gmail ignores MathML |
| Editor preview (`components/markus-ir-preview.tsx`) | a block labelled "Equation (TeX source; drawn on the published page)"; inline equations show as `$` + code + `$`. The preview does not draw MathML because that would need a JavaScript TeX converter. |

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
