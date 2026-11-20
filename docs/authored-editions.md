# Independently authored Story editions

`stories import-edition` is separate from faithful `import-translation`. Use it when
writers tell the same subject differently in each language, with their own leads,
structure and sources. It does not translate, align or rewrite text and calls no model.

```
papyrus stories import-edition --story ORIGINAL_LINEAGE --language es-419 \
  --body-file spanish.md --front-matter-file spanish.yaml \
  --written-by AI --author-kind agent --reason "Independent Spanish reporting" --dry-run --json
```

Omit `--dry-run` to save an unpublished companion. The front matter and body are the
edition's own, including citations, title, dek, images and credits. Agent-authored
copy must declare `drafting: {by: AI}`. No summary is invented. Image files referenced
by the original can be carried; new assets use the normal figure/upload workflow
and publication refuses missing files. A language must already be enabled.

The companion has the original's language group, its own locale address and ordinary
Copywriting checklist. It is not a translation and has no translation alignment,
faithfulness clearance, fictional human translator or fabricated correction pins.
Its own editorial checks, illustration/rating requirements and publication approval
apply. Publication is a separate ordinary action. The public switcher continues to
include only published group members; the original's text and address are unchanged.

A pending translation or existing different edition is a conflict. Repeating the
same import is a no-op; editing uses the ordinary immutable save-version workflow.
Automatic translation, explicit translation requests, bulk backfill and late saves
from already running translations cannot replace authored companions. The strict
faithful translation importer remains unchanged.

This command does not change site settings, enable languages, publish content or
fetch any linked video. A video link remains a link unless an editor explicitly
supplies supported video markup. Normal independent sourcing and rights review
still apply.
