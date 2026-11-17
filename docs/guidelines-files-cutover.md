# Writing guidelines as files: cutting a site over

Schema version 2 of the writing guidelines stores each lineage (the publication's, each section's, each language overlay's) as a set of guideline files in S3 instead of one JSON document (PPY-1d5c43, design: `docs/design/announcement-delivery-design.md` section 5). The engine reads only files. The old JSON shape is read by one module, `src/papyrus_content/guidelines/convert_v1.py`, which exists for this cutover and is deleted when the last site has been converted (with the `convert` command in `guidelines/cli.py`, the `legacy_version` handling in `store.py`, and this page's plan).

## Why the order matters

A site's data API (the image-service function, the announcements function) and the CLI read the same rows. Once the engine that reads files is deployed, a lineage whose current version is still JSON answers `legacy_version` ("saved before guidelines became files"), and the writing guidelines read as unavailable until it is converted. The conversion needs the new upload role (`doctrine_files`, in `amplify/functions/model-attachment-upload`) to be deployed, so the data API deploy comes first and the conversion directly after it. Do both in one quiet window, with no Story being drafted.

## Per-site steps

1. **Before.** `papyrus guidelines history --kind writing` (and for each section) so the current versions are on record. Tell the people who edit guidelines not to save from now until step 5.
2. **Dry run with the new command line.** `papyrus guidelines convert` (new CLI, site still on the old engine: it only reads) lists every lineage with `state: ready` and `resolvedUnchanged: true`. A lineage that is `refused` names the field that does not read back the same (for example a body with Windows line endings): correct it by saving a corrected JSON version while the old engine is still deployed, and dry run again.
3. **Deploy.** Bump the site to the release that carries this change and let its data API deploy finish (the bump carries the new upload role and the file-reading functions together). From here until step 4 the writing guidelines answer `legacy_version`.
4. **Apply.** `papyrus guidelines convert --apply`, signed in as an admin who is a person. Each lineage is saved as its next version naming the version it replaces.
5. **Verify.** `papyrus guidelines resolve --kind writing [--section KEY] [--language TAG]` for the publication, one section and one language: the document is the one before. `papyrus guidelines export --kind writing --dir /tmp/check` shows the files. Run `papyrus guidelines convert` once more: every lineage is `already_files`. The editorial checks drawn from the guidelines are unchanged (the conversion does not touch them).
6. **After the last site.** Remove `convert_v1.py`, the `convert` command and `legacy_version` handling in one change.

## Sites

Which sites hold writing guidelines is read with `papyrus guidelines history --kind writing` on each. A site that never saved any needs nothing: `convert` finds no lineage and its first save is a set of files. Convert one site per release window, each only on the product owner's go, and start with the site that has the fewest lineages.
