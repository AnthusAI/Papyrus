from __future__ import annotations

# Reference text extraction + deletion/filtering loop.
DEFAULT_REFERENCE_FILTER_MODEL = "gpt-6-luna"

# Reference metadata generation/summarization.
DEFAULT_REFERENCE_SUMMARY_MODEL = "gpt-6-luna"

# Editorial constrained rewrite options.
DEFAULT_EDITORIAL_REWRITE_MODEL = "gpt-6-luna"

# Per-role general-purpose models used when a caller supplies none.
DEFAULT_LLM_MODEL = DEFAULT_REFERENCE_FILTER_MODEL
DEFAULT_SMALL_LLM_MODEL = DEFAULT_REFERENCE_SUMMARY_MODEL
