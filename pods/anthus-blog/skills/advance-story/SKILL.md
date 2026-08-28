---
name: advance-anthus-story
description: >-
  Advance an Anth.us newsroom pod story through Kanbus stages. Use when working
  in pods/anthus-blog, moving a story between idea/assignment/research/report/
  editor_select/copywriting/published, or when Kanbus refuses a transition.
---
# Advance an Anth.us newsroom story

Work from the pod root: `pods/anthus-blog/`. Use `kbs` (Kanbus 0.19.1 per
`kanbus-version`). Never edit `project/issues/` or `project/events/` by hand.

## Inspect before acting

1. `kbs show <story-id>` — current stage, title, and guidance.
2. Read `stories/<story-id>/` — which artifacts exist.
3. Read `doctrine/anthus.md` in full when context is thin.

## Stage order

`idea` → `assignment` → `research` → `report` → `editor_select` → `copywriting` → `published`

Supported revision paths return to an earlier stage without deleting prior files.
Copy revision at the copywriting stage is file-based: edit `article.md` while the
story remains in `copywriting`. Do not skip stages; workflow and hooks refuse skip-ahead.

## Artifacts (one directory per story)

| Stage entered via transition | File that must exist before advancing |
| --- | --- |
| `assignment` | `idea.md` |
| `research` | `assignment.md` |
| `report` | `research.md` |
| `editor_select` | `report.md` |
| `copywriting` | `editor_select.md` |
| `published` | `article.md` |

## Advance a story

```bash
cd pods/anthus-blog
kbs update <story-id> --status <next-stage>
```

If Kanbus refuses the transition:

- Read stderr coaching text; it names the missing artifact or illegal skip.
- Write or fix the required markdown under `stories/<story-id>/`.
- Retry the same `kbs update` command.

## Create a new story

```bash
cd pods/anthus-blog
kbs create "Post title" --type story
```

Creation scaffolds `stories/<new-id>/idea.md`. Fill `idea.md`, then move to
`assignment`.

## Boundaries

- No `papyrus` CLI, no AppSync, no hosted newsroom features.
- Internal packets stay in the story directory; publish handoff to
  `Anth.us/src/blog/` is a later slice step.
