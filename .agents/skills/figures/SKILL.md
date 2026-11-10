---
name: figures
description: Draw a diagram, chart or editorial illustration for a Papyrus Story in the site's own design system, as one SVG source rendered to a light and a dark picture, checked by `papyrus figures render`, approved by a person and saved into the Story. Use when a Story would be clearer with a picture that explains something, when an editor asks for a diagram, chart or illustration, or when a copywriting or illustration step calls for a figure.
---

# Figures

> **CLI syntax:** the exact `papyrus` commands, with the flags each takes, are in [docs/agent-cli-guide.md](../../../docs/agent-cli-guide.md) (task `figures`; or run `papyrus guide figures`). `papyrus figures <command> --help` prints a command's real usage. Do not guess a flag.

This skill is the same for every Papyrus site and names no brand. Everything that belongs to one site (its colors, fonts, canvas sizes, role mapping and worked examples) is that site's **design system**, which you read before you draw. The general rules are `papyrus figures rules`; the shape library is `papyrus figures primitives`. Read the rules first, every time: they are short, and they are the acceptance test.

## Two things that never bend

1. **Light and dark are both mandatory.** Every figure ships in a light picture and a dark picture. You draw once, with color *roles* (`fill="{inset}"`, never a hex value), and `papyrus figures render` resolves the one source into both and writes `SLUG.png` and `SLUG.dark.png`. There is no light-only figure. Look at both pictures before you ask for approval, and save both into the Story.
2. **Never invent a brand.** Draw only in the design system of the site you are working on. If the site has none, say so in your note to the person, then either use the stated default (`--neutral-default`: unbranded grays and the machine's own sans-serif, nothing else) or ask them for the design system. Do not make up colors, fonts, logos or a "house style".

## 1. Find the site's design system

Name the site (`papyrus --site SITE_HOST ...`) and find its design system: a folder holding `mapping.json`, the tokens and fonts it names, and optionally worked examples under `examples/NAME/` (each a `figure.svg` and `figure.json`). Today that folder comes from the site's repository or from the person; reading it from the site's backend, beside its mission and policy, is planned and will not change these steps. Read its `mapping.json` (canvas sizes, role names), and open the example closest to what you will draw: copy its structure, not its content.

If you cannot find one, stop and say: "This site has no design system I can read. I can draw with the neutral unbranded default, or you can point me to one." Then do what the person answers. Record which one you used in the Story's agent note.

## 2. Decide whether to draw

Rules section 1 is the test. Draw only when a figure helps the reader understand something that a sentence or a small table would not. A figure never fixes confusing text: rewrite the text first. Consider a rights-cleared photograph, the site's placeholder image or no picture at all. A reader who skips the figure must lose nothing the text does not already say.

Write the acceptance criteria **before** drawing, in `figure.json`: `audience`, `shows` (what it shows and leaves out), `complements` (what it adds to the text beside it) and `surrounding_text` (the sentences in the Story that carry the same information). If you cannot fill all four, do not draw. Each figure answers one question.

## 3. Choose a form

Choose the form for the relationship being explained, not the nearest template (rules section 2): steps in order, a timeline, layers and walls, a change in amount, a place or moment. Compare alternatives side by side, show parts inside a whole with nested fills, and use arrows only when order or direction matters. Vary forms across neighbouring Stories. Phones are portrait: run flow and time top to bottom.

## 4. Draw

Make a folder, for example `./figures/SLUG/`, with:

- `figure.json`: the criteria above plus `slug`, `kind` (`diagram`, `chart` or `illustration`), `alt`, `caption` (one sentence), `credit` (`Drafted by AI. Approved by {approved_by}.` plus a source for facts), `labelled_as` (`none`, `framed`, `forecast`, `invented` or `invented-scene`), `approved_by` (leave `null` until a person approves) and `layout`.
- `figure.svg`: `<title>`, `<desc>`, then the line `<!--primitives-->`; colors only as `{role}` names from the design system's `figure_roles`; type only as `t-<role>` classes; shapes and lines with the meanings in rules sections 3 and 4; one focal mark at most; geometry on a 4px grid; one `<text>` per line, placed by hand.

Stay within the density limits (rules section 9). Try removing each shape, line and label; leave out what the figure survives without. A forecast or an invented example that could pass for data carries its stamp (rules section 10).

## 5. Check and look

```sh
papyrus figures render ./figures/SLUG --design-system ./design-system --check-only
```

Fix every `PROBLEM` and read every `note`. A problem in either theme fails the figure, so a mark that reads in light and vanishes in dark is caught. When it says `ok`, render for real:

```sh
papyrus figures render ./figures/SLUG --design-system ./design-system --out ./pictures
```

The checker cannot tell whether a figure makes sense. Open **both** pictures and look at them at phone width (343px): can you read every word in each, does it still make sense with the color removed, do the rings and marks avoid the letters, is the point obvious in a few seconds? If not, redraw. Do not publish a figure you have not looked at in both themes.

## 6. Get a person's approval

Show the person both pictures and say what they are: the acceptance criteria, the alt text, the caption and the credit. A person confirms each figure before it is published. Set `approved_by` in `figure.json` to the name of the person who approved it (never your own name or an invented one), then render again so the credit is right.

## 7. Save it into the Story

```sh
papyrus figures directive ./figures/SLUG
```

Put the printed `::image{}` line where the figure belongs in the draft. Put `SLUG.png`, `SLUG.dark.png` and `SLUG.figure.json` in the pictures folder and save with `papyrus stories save-version --story LINEAGE --body-file draft.md --images ./pictures --reason "..."`. `save-version` pairs the dark file automatically, and prints a `figure-light-only` warning if you forgot it (a site may refuse the save instead): fix that rather than ignoring it. Show the editor the console link of the saved version, as the other steps do. Never publish without the person's confirmation.

## What you must not do

- Do not draw a light-only figure, or ship a figure whose dark picture you did not look at.
- Do not use a raw color, a font attribute, a gradient, opacity, an outline or a shape for something its meaning does not cover.
- Do not draw in a design system you made up, or pass another site's design system for this one.
- Do not put a figure in a Story without alt text, a caption and the person's approval recorded.
- Do not claim a figure is checked until `papyrus figures render` printed `ok` for the exact source you are saving.
