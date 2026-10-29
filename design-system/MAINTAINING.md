# Maintaining the design system

Repository-only notes. This file is **not** part of the published system —
every other file in this folder is, and an `*.md` at this level becomes a
section page when published, so keep plumbing notes here.

## What this folder is

The source of the Papyrus design system: semantic tokens, the brand book, the
register and scale docs, and the component cards for the shared primitives.
The repository is the source of truth; the published page is a view of it.

| Path | What |
| --- | --- |
| `tokens.json` | the tokens, as data. Colour values are resolved Radix 3.0.0 steps — see the notes in the file |
| `README.md` | the brand book: principles, foundations, usage rules |
| `brands-and-forks.md` | how Papyrus and Threat Intelligence map the same names to different ramps |
| `editorial-scale.md` | the five headline scales and the furniture vocabulary |
| `feed-register.md` | the newsroom feed surface: tone steps, radius scale, flat rules, verdict tones |
| `components/` | `bundle.js` / `bundle.css` / `index.d.ts` plus a card and live preview per component |
| `design-system.json` | the published system's index (title, namespace, preview libraries) |

## Keeping it true to the code

These values were read out of the app, not invented. When the app changes,
this folder is what gets updated:

- colour tokens ← `app/globals.css` `:root` and its dark blocks, which resolve
  to the Radix ramps imported at the top of that file;
- the fork mapping ← `publications/<name>/theme.css` and `lib/site-brand.ts`;
- the feed register ← `components/newsroom-organizer.css` and
  `components/newsroom-theme.css`;
- the headline scales ← `getHeadlineFontSize` in `lib/newspaper-layout.ts`;
- a component card ← the component it documents, named in the card itself.

The tokens are **documentation of the app's tokens, not their generator**.
Nothing in the build reads `tokens.json`; `app/globals.css` is still
hand-written and solver-tuned. Making this file the generator for the app's
custom properties would be its own piece of work, with its own issue.

## Publishing

The page is a Design System artifact at
<https://claude.ai/artifact/8wCm62RGaCPjaSj1oJfwdU> (private; it has to be
shared from the page's Share menu before anyone else can open it).

To refresh it after changing this folder, run `/design-sync` in Claude Code
from the repository root, or ask Claude to publish the changed files to that
url. Everything in this folder except this file maps one to one onto the
artifact's own `project/` paths.
