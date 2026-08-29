# Anth.us blog doctrine (Slice 1)

This pod runs the Anth.us blog through a file-native newsroom workflow before any
hosted Papyrus infrastructure exists.

## Publication boundary

- The pod is upstream. `article.md` in the story workspace is the source of truth.
- Generated MDX under `Anth.us/src/blog/` is build output, not an editing surface.
- Do not edit pod-generated CMS files directly; regenerate from the pod.

## Process versus authority

- Kanbus enforces stage order and artifact gates.
- The pod does not prove who performed editor selection; git history is the audit trail.
- Verified identity and access control belong to hosted Papyrus.

## Voice and scope

- Posts explain how Anthus builds and operates AI systems for real editorial work.
- Research and report artifacts are internal notes; only `article.md` is reader-facing.
- Keep doctrine short enough to read in full every run.

## Board names

When Ryan says the newsroom board or the Papyrus board, he means this publication board (ANTH), not the Papyrus product board (PPY).
