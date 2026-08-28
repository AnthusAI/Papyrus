# Anth.us newsroom pod (Slice 1 kernel)

Kanbus-configured newsroom for dogfooding the Anth.us blog on a laptop. This
directory is its own Kanbus project inside the Papyrus repo so the pattern can
ship as reference config without touching the `papyrus` package.

**Why here, not Anth.us:** Slice 1 needs a standalone pod config tree and a
Papyrus PR. Anth.us remains the publication target (`src/blog/`); this pod owns
process and story workspaces only.

## Requirements

- Kanbus **0.19.1** (`kanbus-version`)
- `kbs` on PATH
- Run all commands from this directory

## Quick verification

```bash
cd pods/anthus-blog
kbs validate
kbs hooks validate

# Legal path: create story, fill idea.md, advance to assignment
kbs create "Slice 1 kernel demo" --type story
STORY_DIR=$(ls -t stories | head -1)
printf '# Idea\n\nDemo pitch for kernel verification.\n' > "stories/${STORY_DIR}/idea.md"
kbs update "$STORY_DIR" --status assignment

# Illegal skip-ahead: idea → copywriting (blocked with coaching)
kbs create "Skip-ahead demo" --type story
SKIP_DIR=$(ls -t stories | head -1)
kbs update "$SKIP_DIR" --status copywriting || true
```

Expect the last command to fail and stderr to mention copywriting requires
editor selection and the stage ladder.

## Layout

- `.kanbus.yml` — story type and stage machine
- `project/policies/` — coaching and skip-ahead policy rules
- `hooks/` — fail-closed artifact gates (files the policy DSL cannot see)
- `skills/advance-story/SKILL.md` — agent instructions
- `doctrine/anthus.md` — publication doctrine (read in full each run)
- `stories/<story-id>/` — per-story markdown artifacts

## Agent skill

Use `skills/advance-story/SKILL.md` when advancing work in this pod.
