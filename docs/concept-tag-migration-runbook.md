# Runbook: migrate concept tags from `related_to` to `tagged_with`

Ryan, 2026-11-09: one predicate, one meaning (PPY-dde133). Every writer now writes `tagged_with` for a story or Reference tagged with a concept, and every reader accepts both
names. This runbook moves the rows that were written under `related_to` before the rename. Design and rules: [Tagging with concepts](story-reporting.md#tagging-with-concepts).
Code: `src/papyrus_content/concept_tag_migration.py`.

The migration is an operator command (IAM lane): editors cannot update relations. It never deletes anything. Run it per site backend.

## Order

1. **Release the PR.** The Papyrus release carries the command, the writers and the readers (Python and TypeScript). Merge and release as usual.
2. **Deploy the TypeScript change to the site backend** through the normal Amplify release of that site (the `createReferenceLink` mutation must write `tagged_with`, and the console
   must read it). Do this before the migration, or the console keeps writing legacy rows behind it. A console that is not deployed yet still works: the server accepts
   `related_to` for a concept and writes `tagged_with`, and the Python side accepts both.
3. **Count what is left**, read only:
   ```bash
   papyrus stories check-links --legacy-only
   papyrus references check-links --corpus-id knowledge-corpus-<key> --legacy-only
   ```
4. **Dry run** (the default; it writes nothing, only a report file):
   ```bash
   papyrus relations migrate-concept-tags            # add --site KEY or --corpus-key KEY to keep one corpus's References
   ```
   It prints the number of legacy tags, the counts by subject kind (`item` is a story), state (`current`, `suggested`, `rejected`) and provenance, the planned actions
   (`migrate`, `resume`, `retire-only`) and a sample, and writes `.papyrus-runs/concept-tag-migration-<time>/migration-report.json` with one entry per edge.
5. **Show Ryan the counts.** Do not apply before he has seen them.
6. **Apply**, in batches if wanted (each run is idempotent and resumable):
   ```bash
   papyrus relations migrate-concept-tags --apply --limit 500
   papyrus relations migrate-concept-tags --apply            # the rest
   ```
   Each edge is written as `tagged_with` first and the old row is retired second, so a stop between the two leaves both visible and the next run finishes it (`resume`). A failed
   write stops the run, the report names the edge, and running it again goes on.
7. **Verify**:
   ```bash
   papyrus relations migrate-concept-tags             # dry run again: "legacy related_to tags found 0"
   papyrus stories check-links --legacy-only          # 0 legacy related_to tag(s) still to migrate
   papyrus references check-links --corpus-id knowledge-corpus-<key> --legacy-only
   ```
   Open a concept page and a story page that were tagged before: the same concepts and "Linked by editors" appear.

## What happens to each row

| Legacy row (`related_to`, story or Reference to concept) | New row (`tagged_with`) | Legacy row after |
|---|---|---|
| `current` (confirmed by a person, or derived) | `current`, same provenance, decision, words | `superseded` |
| `suggested` (vector suggestion, awaiting a person) | `suggested`, same score and classifier | `superseded` |
| `rejected` | `rejected`, same decision and reason, so no writer revives it | `superseded` |

`related_to` between two References, and between two concepts, is not touched. A `tagged_with` row that already exists for the pair (an interrupted run, or a tag made after the
rename) is kept as it is, and only the legacy row is retired.

## Undo

Nothing is deleted. A retired row keeps its content, `supersededBy` and `supersededAt`; setting its `relationState` back to the earlier state and its four state keys to match
(and removing the new row) restores the view. This is a data fix by hand; none is expected.

## Limits

The command reads the concept list once (the one table read), then three index partitions per concept, 25 to a request. There is no whole-relation scan. A site with thousands of
concepts takes a few hundred index requests for a dry run.
