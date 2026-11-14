"""Download the models a run needs into HF_HOME at pinned revisions (build time only)."""

from pathlib import Path

from huggingface_hub import constants, snapshot_download

MODELS = (
    ("sentence-transformers/all-MiniLM-L6-v2", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41", None),  # the BERTopic embedder
)

for repository, revision, patterns in MODELS:
    path = snapshot_download(repository, revision=revision, allow_patterns=patterns)
    # Offline lookups of "main" read refs/main, which a download by revision does not write.
    refs = Path(constants.HF_HUB_CACHE) / f"models--{repository.replace('/', '--')}" / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(revision)
    print(f"baked {repository}@{revision[:8]} -> {path}")
