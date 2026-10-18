# Reference Processing Terminology

Use this vocabulary contract for Papyrus reference workflows.

## Core Terms

- `reference processing`: the full pipeline from sparse reference seed to
  usable knowledge reference.
- `process reference`: operator verb for running that pipeline.
- `register reference`: create the initial `Reference` row from DOI/URL/sparse
  metadata.
- `resolve source`: find the canonical source artifact (for example, PDF URL).
- `acquire source`: download and store the source artifact in corpus storage.
- `extract text`: run extraction (GROBID for PDFs) and store text artifacts.
- `expand citation graph`: upsert authors, cited references, and relations from
  structured extraction.
- `curate reference`: editorial accept/reject/archive decisions only.
- `note`: a `Message` with `messageKind = "note"`. A note about a reference,
  concept or other record is linked to it by a `note_about` semantic relation.
  Notes have no surface of their own; they appear in the Messages tab and can
  be filtered by `messageDomain`.

## Reserved Meanings

- `ingest`: Biblicus corpus accession/storage term.
- `import`: config/artifact/type/projection transfer into Papyrus.
- `curation`: editor decision layer, not source processing mechanics.

## Operator Sentence Patterns

- "Process this DOI" means run register/resolution/acquisition/extraction/graph
  expansion for that reference.
- "Register this DOI" means create the initial sparse reference only.
- "Reprocess this reference" means rerun processing steps without changing
  curation semantics.
- "Curate this reference" means editorial status decision, not extraction work.
