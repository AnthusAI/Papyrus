# Knowledge components

The standard front end renders the publication's knowledge snapshot (trending entities, emerging themes, a concept of the week, an entity's trend, relations and related items) as ordinary server-rendered HTML. Nothing needs JavaScript, nothing is fetched in the browser, and a component whose data is absent renders nothing, so the page keeps its own placeholder. Part of [Building a Papyrus static site](building-a-papyrus-static-site.md).

## Data

`papyrus knowledge snapshot` writes these files into the site store (or a directory). A projection reads them and never writes them.

| File | Read by |
|---|---|
| `_data/knowledge/index.json` | every block except `knowledge-clusters`, and the concept directives |
| `_data/knowledge/clusters.json` | `knowledge-clusters` |
| `_data/knowledge/entities/<key>.json` | `knowledge-entity` |

All three have `schemaVersion: 1`; another version, or invalid JSON, is a build error that names the file. Each file is read once per projection run.

Where the files come from:

- **Deployed and `--out` builds:** the site store the projection writes to (`writer.get`), so `_data/knowledge/` next to the pages, under `urls.basePath` when the site has one (`posts/_data/knowledge/`). Reconcile must leave `_data/knowledge/` alone.
- **Local builds:** `papyrus ops content project --all --knowledge-dir DIR`, with `index.json`, `clusters.json` and `entities/` directly under `DIR`.

A page that reads the snapshot is re-rendered when the files it reads change: the digest of `index.json` and `clusters.json` is part of every generated page, and the digest of the entity files a page names with `knowledge-entity` is part of that page.

## Blocks

Place a block in a page file, or in an item after a `::band` line, with `::include{kind="block" name="..."}`. Attribute values may be quoted or bare (`limit=5`). The block never needs the site's `block` hook; the hook still serves every other name. An unknown attribute is a build error that names the file. The Markdown twin of the page keeps the include line as written.

| Block | Attributes | Reads | Output |
|---|---|---|---|
| `knowledge-trending-strip` | `limit` (5) | index | `ul.papyrus-knowledge-trending-strip`: for each entity of `trending`, in the snapshot's order, a chip and its trend |
| `knowledge-trending-list` | `limit` (6), `entityKind` (all kinds) | index | `div.papyrus-knowledge-trending-list > ol`: rank, chip, trend, `N items` and `N in the last 4 weeks`. Entities marked `isNew` are left out. With `entityKind` the list holds only that kind. Without it, and with more than one kind present, a `nav.papyrus-knowledge-kindfilter` of links filters the list by `:target` with no script (an inline `<style>` of one rule per kind); the "All" link clears it |
| `knowledge-clusters` | `limit` (3) | clusters | `ul.papyrus-knowledge-clusters`: name (linked when the cluster has an `href`), item count, top terms, sparkline, a New, ▲ Growing or ▼ Cooling label, and who accepted it ("Accepted by AI"). A cluster with a `name` is shown. Without one it is hidden, or "Unnamed theme" with its item count when `unacceptedClusters` is `unnamed`. A cluster with fewer than 4 `weeksOfData` has no label and no sparkline |
| `knowledge-concept-of-the-week` | none | index | `article.papyrus-knowledge-cotw`: name, lede, who edited the description ("Edited by AI on 2026-10-21", or "Reviewed by Ada on 2026-10-21" for a person), item and maker counts; nothing when `conceptOfTheWeek` is null |
| `knowledge-topic-count` | none | index | `span.papyrus-knowledge-count` with `topicCount` |
| `knowledge-entity` | `key`, `part` (`trend`, `neighbourhood`, `related` or `provenance`), for `trend`: `annotate` (a date), `annotateLabel` | entity, and index for the kind labels, links and `asOf` | `trend`: the sparkline and percent, and the chart after 12 weeks. `neighbourhood`: one column per relation type. `related`: a list of linked titles with their dates. `provenance`: who accepted the entity and who edited its description |
| `knowledge-score` | `value` (0 to 1), `n`, `threshold` (0.5), `label` | none | a score readout for a value the author gives |

```markdown
::band{size="bare"}
## Moving this month
::include{kind="block" name="knowledge-trending-strip" limit=5}
::include{kind="block" name="knowledge-trending-list" limit=6 entityKind=""}
::include{kind="block" name="knowledge-clusters" limit=3}
::include{kind="block" name="knowledge-concept-of-the-week"}
::include{kind="block" name="knowledge-entity" key="acme-loom" part="trend" annotate="2026-09-24" annotateLabel="Launch"}
```

## Cold-start states

| Weeks of history | Sparkline | Percent | Chart |
|---|---|---|---|
| under 4 | none | none | none; the chip says "new" |
| 4 to 7 | yes (only the weeks since the first link) | none (the snapshot's `change.percent` is null under 8 weeks) | none |
| 8 or more | yes | yes when the snapshot has one (`change.percent` is null when the prior four weeks hold fewer than 5 items) | none |
| 12 or more | yes | as above | the weekly chart |

Cluster labels follow the same floor: nothing under 4 weeks of data. The reader never recomputes a number; it shows what the snapshot holds. The percent rule (a base of 5 items and 8 weeks of history) lives in the snapshot; the components decide only whether to draw a sparkline.

## Components

The blocks are built from pure functions in `papyrus_content.projection.standard.knowledge_components`, usable from a site's hooks:

- `entity_chip(kind_label, name, kind=, href=, proposed=)`: kind and name. A proposed entity has a dashed outline and the visually hidden text "(proposed)".
- `sparkline(values)` and `trend(entity)`: an inline SVG polyline, `aria-hidden`, beside the figure as text: `▲ +40%`, `▼ −25%` or `▬ 0%`. The mark is announced as "up", "down" or "unchanged".
- `trend_chart(series, weeks, as_of, annotate=, annotate_label=)`: an inline SVG with two series, bars for the items per week and a dashed line for their trailing four-week average, both computed from the one weekly series of the snapshot. A text summary is the SVG's label and the figure's caption. The annotated week gets a vertical marker and the label.
- `neighbourhood(neighbours, kinds, links)`: one column per relation type (the heavier relation first, and its label made readable: `built_on` is "Built on"), entries by weight (the number of items linking both ends) with a bar and the number. The snapshot holds only accepted relations.
- `score_readout(value, n, threshold=, label=)`: a 5-segment meter, the value and `n` as text, dimmed below the threshold with "(below threshold)" for assistive technology.

## Concept directives in a static build

`::recent-concepts{limit=10 kind=...}`, `::concept-list{kind=... limit=...}` and `::concept-count{kind=...}` in an item or page file render from `index.json`:

- `concept-count`: the accepted entity count (`entityCount`, or the count of `kind` in `kinds`) in `span.papyrus-knowledge-count`.
- `recent-concepts`: the entities most recently first linked (fewest `weeksOfHistory`, then most items), `limit` of them.
- `concept-list`: the entities by name.

Both lists are `ul.papyrus-knowledge-concepts` of chips with their item counts. Without `index.json` each directive is the empty `div.papyrus-dynamic` it always was; the CMS wiki view still fills it. The `.md` twin keeps the directive as written.

## Theming

`css/papyrus-knowledge.css` is published and linked after `css/markus-components.css` (both follow `componentsCss`). Set these custom properties in your theme; each has a fallback.

| Property | Used for |
|---|---|
| `--papyrus-knowledge-ink` | chip text |
| `--papyrus-knowledge-muted` | kind labels, counts, captions |
| `--papyrus-knowledge-rule` | chip and card outlines, list rules, chart axis |
| `--papyrus-knowledge-accent` | hover and marker emphasis (never the only signal) |
| `--papyrus-knowledge-line` | sparkline, weight bar fill, meter, chart line |
| `--papyrus-knowledge-bar` | chart bars |
| `--papyrus-knowledge-track` | weight bar track |
| `--papyrus-knowledge-chip-bg`, `--papyrus-knowledge-chip-size`, `--papyrus-knowledge-radius` | chips and filter links |
| `--papyrus-knowledge-card-radius` | cluster cards |
| `--papyrus-knowledge-gap` | gaps of the strip, the cluster grid and the neighbourhood |
| `--papyrus-knowledge-dim` | opacity of a low score |

Style by class when you need more: `papyrus-knowledge-chip` (`--proposed`), `-trend`, `-sparkline`, `-change`, `-new`, `-trending-strip`, `-trending-list`, `-kindfilter`, `-clusters`, `-cluster`, `-cotw`, `-count`, `-neighbourhood` (`-column`, `-heading`), `-weightbar`, `-weight`, `-score` (`--dimmed`), `-chart`, `-related`, `-concepts`, and `papyrus-knowledge-sr` for text that only assistive technology reads.
