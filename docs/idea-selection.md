# Choosing which ideas become Stories

Many ideas arrive every day, and a Story an editor picks runs through every stage to just before publishing. So the first step has to be picky. `papyrus ideas select` is that step: the editor agent reads a section's ideas and picks only the best, and picking none is a normal result.

```bash
papyrus ideas select --section SECTION --dry-run
papyrus ideas select --all-sections --recent-section 30d --recent-site 5s --max-new-stories 1 --per-days 1
```

`--dry-run` calls the model and writes nothing.

## What it compares

One model call per section, from the editor's [context pack](newsroom-context-packs.md):

- the publication's mission and policy
- the section's mission, policy, assignment guidance and kill criteria
- recent Stories published in the section, and across the site
- the section's accepted References, and the Stories already in progress
- the other ideas, so two on one subject do not both go through

An editor's stars are a strong signal, and the ideas with stars are read first. They are not a pick.

## The settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `--recent-section` | `30d` | What counts as recent in the section: days (`30d`) or the newest Stories (`5s`) |
| `--recent-site` | `30d` | The same across the site |
| `--max-new-stories` | `1` | New Stories allowed in a section in the window |
| `--per-days` | `1` | The length of that window |

The 30 days is a starting point to experiment with. Each decision records the settings it ran with, so runs can be compared.

## The rate limit

The limit counts every Story in the section that left the idea stage in the window, whether a person or this step moved it. At the limit, no model is called. It is a ceiling, and the agent is told so.

## What a decision does

- **Picked.** The reason and settings go on the version's `metadata.selection`, a research assignment is created with the agent's direction, and the Story moves to the assignment stage as `automation:idea-selection`. A person can undo it by moving the Story back or spiking it.
- **Declined.** The reason goes on the version and the idea stays at the idea stage. It is not read again until it has a new version, or someone passes `--again`. Nothing is spiked.
- **Over the limit.** If the model picks more than the room left, the extras are reported and nothing is recorded on them, so the next pass reads them again.

A person can always pick by hand with `papyrus stories assign-research`.
