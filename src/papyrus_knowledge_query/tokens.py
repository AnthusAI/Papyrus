from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_TIKTOKEN_ENCODING = "o200k_base"


@dataclass(frozen=True)
class TokenCounter:
    """Token counter backed by tiktoken, so context budgets track model-token behavior.

    tiktoken is a declared dependency. When it cannot be imported or the encoding cannot be loaded, the query fails with that error;
    there is no approximate count to fall back on.
    """

    tokenizer_model: str = ""
    encoding_name: str = DEFAULT_TIKTOKEN_ENCODING

    def with_model(self, tokenizer_model: str | None = None) -> "TokenCounter":
        model = (tokenizer_model or os.environ.get("PAPYRUS_TOKENIZER_MODEL") or "").strip()
        return TokenCounter(tokenizer_model=model, encoding_name=self.encoding_name)

    def metadata(self) -> dict[str, str]:
        metadata = {"provider": "tiktoken", "encoding": str(getattr(self._encoding(), "name", self.encoding_name))}
        if self.tokenizer_model:
            metadata["model"] = self.tokenizer_model
        return metadata

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._encoding().encode(text))

    def truncate(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0 or not text:
            return ""
        encoding = self._encoding()
        token_ids = encoding.encode(text)
        if len(token_ids) <= max_tokens:
            return text
        return encoding.decode(token_ids[:max_tokens]).rstrip()

    def _encoding(self):
        # Imported where it is used, not at module load: the monitoring router bundles this package for its vector pass, which never counts tokens,
        # and it carries no native wheels. Counting without tiktoken raises the ImportError.
        import tiktoken

        if self.tokenizer_model:
            return tiktoken.encoding_for_model(self.tokenizer_model)
        return tiktoken.get_encoding(self.encoding_name)
