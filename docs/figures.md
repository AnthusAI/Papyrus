# Figures

A figure is a diagram, chart or editorial illustration for a Story, drawn as one SVG source and rendered to a light picture and a dark picture. This page says what belongs to Papyrus, what belongs to a site, how to render and check a figure, and what is not built yet. The agent workflow is the [figures skill](../.agents/skills/figures/SKILL.md); command recipes are in [agent-cli-guide.md](agent-cli-guide.md) (`papyrus guide figures`). Story PPY-74ef89 tracks the whole feature; this is its first slice.

## Papyrus owns the rules, the site owns the design system

| Belongs to Papyrus (the same for every site) | Belongs to a site (its *design system*) |
| --- | --- |
| The rules: `papyrus figures rules` (`src/papyrus_content/data/figures/rules.md`). They name roles, never colors or fonts. | `mapping.json`: the role names (`ground`, `inset`, `ink`, `focal` ...), type roles (`head`, `label` ...) and canvas sizes. |
| The shape library: `papyrus figures primitives` (glyphs, arrowhead, hatch and dot patterns). | The tokens: every color has a light and a dark value; type styles. Inline in `mapping.json` (`"tokens"`) or in a file it names (`"tokens_file"`). |
| The checks and the renderer (`src/papyrus_content/figures/`). | The font files it names, which are embedded in the picture. |
| | Worked examples: `examples/NAME/figure.svg` and `figure.json`. |

A site with no design system uses `--neutral-default` (unbranded grays and the machine's own sans-serif, no logos) and says so, or asks for one. Nobody invents a brand.

## Light and dark are both mandatory

Every figure ships in a light picture and a dark picture. One source, drawn with color roles, resolves to both, so the two share one geometry and one aspect ratio. `papyrus figures render` has no one-theme mode, measures each theme separately and fails the figure on a problem in either. A design system that gives a color no dark value is refused when it is loaded. `stories save-version` warns when a figure is saved with only a light picture.

## Rendering

```sh
papyrus figures render ./search-nobody-sees --design-system ./design-system --out ./pictures
```

The figure folder holds `figure.svg` (colors as `{role}`, type as `t-<role>` classes, `<!--primitives-->` after `<desc>`) and `figure.json` (audience, what it shows, what it adds, the surrounding text, alt, caption, credit, label kind, approver, layout). The source is checked first. Then, for each theme, the SVG is put in a page with the design system's fonts embedded as data, laid out in headless Chromium (Playwright; Chrome works when no Chromium is installed), and **measured**: text size on a phone, text at the margin or hanging over the edge of the shape behind it, contrast of each label against what is really under it, overlapping labels, line weight. The picture is a screenshot at the design system's `export_scale` (2) times the canvas, with transparent corners. On success it writes `SLUG.png`, `SLUG.dark.png` and `SLUG.figure.json`; the last marks the pictures as a figure for `save-version`.

Output is `SLUG: PROBLEM: ...` lines (the figure fails and the command exits 1), `SLUG: note: ...` advice, and `SLUG: ok` or `SLUG: FAILED`. `--json` prints the same as data, which is what a hosted renderer will return. `--check-only` writes nothing. The checks cannot judge whether a figure makes sense; a person looks at both pictures and approves.

Rendering needs `pip install playwright` and a Chromium (`playwright install chromium`) or Google Chrome. Only this command imports Playwright.

## Saving into a Story

`papyrus figures directive FOLDER` prints the `::image{}` line. Put the pictures and the sidecar in a folder and `papyrus stories save-version --story LINEAGE --body-file draft.md --images ./pictures --reason "..."`. The `.dark.png` next to `SLUG.png` is paired automatically. A picture with a `SLUG.figure.json` beside it is a figure; if its dark picture is missing, `save-version` prints `figure-light-only ... WARNING: ...` and still saves. `--require-dark-figures` (or `PAPYRUS_REQUIRE_DARK_FIGURES=1`) refuses the save instead, before anything is uploaded. An ordinary photograph with no dark picture is never warned about.

## The loading seam

`papyrus_content.figures.design_system.DesignSystemSource` has three methods: `read_text(name)`, `read_bytes(name)` and `list_examples()`, all by a path relative to the design system's root. `DirectorySource` is the only source today (`--design-system DIR`). A source that reads a site's design-system records through the signed-in CLI implements the same three methods; `load_design_system(source)` validates whatever it returns (roles, tokens, a dark value for every color) and nothing else changes.

## Not built yet

- The design system as backend data, read through the signed-in CLI and the context pack, and published from a site repository at deploy.
- Hosted rendering for an agent with no browser, and a site setting that refuses a light-only figure (today the refusal is a flag or an environment variable).
- Moving Machines on Machines onto this and removing its copies of the rules, primitives, mapping and renderer.
- The p.apyr.us documentation page.
