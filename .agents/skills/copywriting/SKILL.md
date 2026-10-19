---
name: copywriting
description: Turn Papyrus reporting into attributed, versioned article copy using current editorial context and the existing Limatus copy-edit loop.
---

# Copywriting

Resolve the intended publication and story lineage using its configuration and live records. Read its reporting Messages, current draft, cited References and open questions. Do not substitute assumptions for missing reporting.

Fetch guidance before writing:

```bash
papyrus editorial context --backend cloud --publication PUBLICATION_KEY --story STORY_LINEAGE --format json
```

Use the returned `text`, precedence, warnings and source revisions; record `contextHash` and source identity in a story Message. Required-policy or authorization failures stop the writing pass. For explicitly offline work, `--backend local --publication PUBLICATION_KEY [--section SECTION_ID]` reads Git configuration and is labeled local, not current hosted policy. Never silently substitute seeds for unavailable hosted guidance. Policy text stays in the publication, not this skill.

Write from the reporting evidence, preserving source qualifications and citation keys. Keep private doctrine and reporting notes out of reader copy. Save every substantial article change through `papyrus stories save-version`, with a reason and accurate author attribution; preserve prior versions. Report unresolved evidence gaps as Messages, scoped with `--reference REFERENCE_LINEAGE` and `--version N`. Citation role and classifier feedback remain independent.

For copy editing, read `limatus skill` (or `python -m limatus skill`) and follow its packaged `limatus-copy-edit-loop`. Select the publication's existing style profile and rewrite configuration; missing profile selection is a gap to resolve, not permission to invent house style. Use its scan → decisions → options → compare workflow. Keep the original immutable. Its current human selection requirement remains: recommend options, and only apply a specifically authorized option/id/anchor to a separate working copy. Compare ranking alone does not authorize application. Run profile-directed title/subtitle work after body edits and use the profile's field mapping (Papyrus subtitle is `deck`).

After authorized edits, save a new Papyrus version, record the editing decisions and context provenance, and read back the result. Keep the assigned stage and unpublished status unless separately authorized. Never publish as a side effect of writing or editing.
