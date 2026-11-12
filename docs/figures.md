# Figures

A figure is a diagram, chart or editorial illustration for a Story, drawn as one SVG source and rendered to a light picture and a dark picture. This page says what belongs to Papyrus, what belongs to a site, how to render and check a figure, and what is not built yet. The agent workflow is the [figures skill](../.agents/skills/figures/SKILL.md); command recipes are in [agent-cli-guide.md](agent-cli-guide.md) (`papyrus guide figures`). Story PPY-74ef89 tracks the whole feature; this covers its first two slices.

## Papyrus owns the rules, the site owns the design system

| Belongs to Papyrus (the same for every site) | Belongs to a site (its *design system*) |
| --- | --- |
| The rules: `papyrus figures rules` (`src/papyrus_content/data/figures/rules.md`, or the site's own, see below). They name roles, never colors or fonts. | `mapping.json`: the role names (`ground`, `inset`, `ink`, `focal` ...), type roles (`head`, `label` ...) and canvas sizes. |
| The shape library: `papyrus figures primitives` (glyphs, arrowhead, hatch and dot patterns). | The tokens: every color has a light and a dark value; type styles. Inline in `mapping.json` (`"tokens"`) or in a file it names (`"tokens_file"`). |
| The checks and the renderer (`src/papyrus_content/figures/`). | The font files it names, which are embedded in the picture. |
| | Worked examples: `examples/NAME/figure.svg` and `figure.json`. |

A site with no design system uses `--neutral-default` (unbranded grays and the machine's own sans-serif, no logos) and says so, or asks for one. Nobody invents a brand.

## Light and dark are both mandatory

Every figure ships in a light picture and a dark picture. One source, drawn with color roles, resolves to both, so the two share one geometry and one aspect ratio. `papyrus figures render` has no one-theme mode, measures each theme separately and fails the figure on a problem in either. A design system that gives a color no dark value is refused when it is loaded. `stories save-version` warns when a figure is saved with only a light picture, and refuses it when the site's `requireDarkFigures` setting is on.

## Rendering

```sh
papyrus figures render ./search-nobody-sees --out ./pictures                              # the signed-in site's stored design system
papyrus figures render ./search-nobody-sees --design-system ./design-system --out ./pictures   # a folder overrides it
```

The figure folder holds `figure.svg` (colors as `{role}`, type as `t-<role>` classes, `<!--primitives-->` after `<desc>`) and `figure.json` (audience, what it shows, what it adds, the surrounding text, alt, caption, credit, label kind, approver, layout). The source is checked first. Then, for each theme, the SVG is put in a page with the design system's fonts embedded as data, laid out in headless Chromium (Playwright; Chrome works when no Chromium is installed), and **measured**: text size on a phone, text at the margin or hanging over the edge of the shape behind it, contrast of each label against what is really under it, overlapping labels, line weight. The picture is a screenshot at the design system's `export_scale` (2) times the canvas, with transparent corners. On success it writes `SLUG.png`, `SLUG.dark.png` and `SLUG.figure.json`; the last marks the pictures as a figure for `save-version`.

Output is `SLUG: PROBLEM: ...` lines (the figure fails and the command exits 1), `SLUG: note: ...` advice, and `SLUG: ok` or `SLUG: FAILED`. `--json` prints the same as data, which is what a hosted renderer will return. `--check-only` writes nothing. The checks cannot judge whether a figure makes sense; a person looks at both pictures and approves.

Rendering needs `pip install playwright` and a Chromium (`playwright install chromium`) or Google Chrome. Only this command imports Playwright.

With neither `--design-system` nor `--neutral-default`, `render` reads the design system the signed-in site stores and prints a `figures: using the site's stored design system ... version N` line on stderr. A folder given with `--design-system` overrides it. If the site stores none, or cannot be read, the command stops and says why; it never falls back to the neutral default or to a made-up style.

## The design system as backend data

A site's design system is one more guideline document (kind `design-system`), stored the way mission, policy and the other guidelines are (guidelines as data, epic PPY-2a2a8a, `src/papyrus_content/guidelines/`). The database holds one catalog row per version (`Item`, type `doctrine`, slug `editorial-doctrine-design-system`, with `tenantSlug` on a tenant site): the version, who saved it, when, why and a content hash. Its `bodyMarkus` and `metadata` stay empty. The content is in S3, attached to that version as ModelAttachments:

- one JSON **document** (role `doctrine_document`) holding every text file of the design system verbatim, by path (`mapping.json`, the tokens file, each example's `figure.svg` and `figure.json`), the site's figure settings, and each font's hash and size; and
- one **asset** (role `doctrine_asset`) for each font file.

The content hash covers the fonts through their hashes, and a font that does not match its hash is refused when read. No new table, index or subscription is used: a read is a query on the slug index, a query on the attachment owner index and the downloads. Saving a design system that gives a color no dark value, names a missing font, or has an unknown setting is refused and stores nothing; an unchanged folder makes no new version; every change is a new version and the old ones stay readable.

```sh
papyrus design-system show [--version N] [--json]      # version, roles, fonts, examples, settings, or that the site has none
papyrus design-system pull ./design-system             # write the stored files back as a folder
papyrus design-system push ./design-system --reason "..."   # publish a folder as the next version (--dry-run previews)
```

The site's repository stays the place where the design system is edited, and runs `push` as part of its deploy. A folder is `mapping.json`, its tokens file, the fonts it names, `examples/NAME/figure.svg` + `figure.json`, and an optional `settings.json`. A folder with no `settings.json` keeps the site's current settings; `{"requireDarkFigures": false}` turns the setting off. The editorial context (`papyrus editorial context`) carries a short pointer to the design system, built from the catalog row alone, so an agent knows it exists and how to read it.

The site settings are `requireDarkFigures`, `illustrationRequireApprovalCredit` (off unless set: then the cover needs a recorded approval and an `Approved by NAME` line on its image) and `illustrationRequiredTypes` (a list of Story types whose checklist needs an approved cover before publishing, `["article"]` when unset; see [the Illustration step](story-procedure.md#the-illustration-step)), for example `{"requireDarkFigures": true, "illustrationRequiredTypes": ["article", "post"]}`. A stored cover closes that step with no approval needed (unless the site opts in with `illustrationRequireApprovalCredit`), and where `requireDarkFigures` is on a figure's dark picture must be stored too.

## Saving into a Story

`papyrus figures directive FOLDER` prints the `::image{}` line. Put the pictures and the sidecar in a folder and `papyrus stories save-version --story LINEAGE --body-file draft.md --images ./pictures --reason "..."`. The `.dark.png` next to `SLUG.png` is paired automatically. A picture with a `SLUG.figure.json` beside it is a figure; if its dark picture is missing, `save-version` prints `figure-light-only ... WARNING: ...` and still saves. The save is refused instead, before anything is uploaded, when the site's `requireDarkFigures` setting is on, or when `--require-dark-figures` or `PAPYRUS_REQUIRE_DARK_FIGURES=1` is given. The flag and the variable are overrides: `PAPYRUS_REQUIRE_DARK_FIGURES=0` saves a light-only figure even where the site refuses it. The setting is read (one index query and one download) only when a figure has no dark picture and nothing overrides it; if it cannot be read, the save stops and says so rather than guessing. An ordinary photograph with no dark picture is never warned about.

## The loading seam

`papyrus_content.figures.design_system.DesignSystemSource` has three methods: `read_text(name)`, `read_bytes(name)` and `list_examples()`, all by a path relative to the design system's root. `DirectorySource` is the only source today (`--design-system DIR`). `DirectorySource` reads a folder (`--design-system DIR`); `BackendSource` (`papyrus_content.figures.records`) answers the same three methods from the stored document and fonts, fetching and checking a font only when it is asked for. `load_design_system(source)` validates whatever it returns (roles, tokens, a dark value for every color) and nothing else changes.

## Not built yet

- Hosted rendering for an agent with no browser (the next slice): it will take a figure's source and a site's stored design system and return both pictures and any problems.
- Moving Machines on Machines onto this and removing its copies of the rules, primitives, mapping and renderer.
- The p.apyr.us documentation page.

## A site's own figure rules

The general rules above are the default. A site that draws by different rules saves its own with `papyrus guidelines save --kind figure-rules --file rules.yml --reason "..." --expected-current-version-id none`, where the file is `{schemaVersion: 1, bodyMarkus: "<the complete text>"}`. The site's text replaces the general rules for that site (nothing is merged), is versioned like the other guidelines, and is what `papyrus figures rules` prints for that site. `papyrus figures rules --packaged` prints the general rules.
