# Biblicus 1.14 upgrade

Papyrus requires `biblicus >=1.14.1,<2` from PyPI. Biblicus now validates corpus catalogs strictly
and never interprets item `metadata`, so Papyrus keeps all of its own catalog fields under
`metadata.papyrus`.

## What changed in Papyrus

- Catalog item extension fields (`subtitle`, `summary`, `identifiers`, `identifier_resolution`,
  `title_subtitle`, `title_subtitle_resolution`, `summary_resolution`, `quality_rating`) are written
  to `metadata.papyrus` and read from there.
- `_preflight_biblicus_catalog_compatibility` is gone; Biblicus itself rejects malformed catalogs.
- Catalogs are located with `Corpus.catalog_path` (`metadata/catalog.json`). The `.biblicus/catalog.json`
  and mixed-case corpus folder fallbacks are gone.
- Graph snapshot manifests and extraction snapshot folders are located with the `Corpus` layout accessors.
- Biblicus subprocesses use the installed package. A sibling checkout is only used when
  `BIBLICUS_WORKDIR/src/biblicus` exists, and `BIBLICUS_WORKDIR` remains the directory holding `corpora/`.
- GROBID auto-start uses `BIBLICUS_GROBID_URL`, `BIBLICUS_GROBID_CONTAINER_NAME` and
  `BIBLICUS_GROBID_DOCKER_IMAGE`. The default container is now `biblicus-grobid`; the old
  `PAPYRUS_GROBID_*` variables are no longer read.

## Migrating existing corpora

Corpus data lives outside this repository, so run these once per corpus (Pilobol.us and Papyrus),
from a checkout of Biblicus 1.14.1 or later and this repository. Back up each corpus first.

```bash
CORPUS="$BIBLICUS_WORKDIR/corpora/<corpus-folder>"

python /path/to/Biblicus/scripts/migrate_catalog_extensions.py "$CORPUS" --dry-run
python /path/to/Biblicus/scripts/migrate_catalog_extensions.py "$CORPUS"

python scripts/migrate_catalog_papyrus_namespace.py "$CORPUS" --dry-run
python scripts/migrate_catalog_papyrus_namespace.py "$CORPUS"

biblicus --corpus "$CORPUS" list
```

If a corpus folder still uses a mixed-case name, rename it to the lowercase kebab-case name that
`corpora/papyrus-steering.yml` expects. If an old `.biblicus/catalog.json` exists, move it to
`metadata/catalog.json`.
