from __future__ import annotations

import os
import sys
from pathlib import Path

from .env import BIBLICUS_ROOT


def biblicus_python_executable() -> str:
    for candidate in (
        BIBLICUS_ROOT / ".venv" / "bin" / "python",
        BIBLICUS_ROOT / ".venv" / "bin" / "python3",
    ):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def environment_with_biblicus_source_checkout(environment: dict[str, str]) -> dict[str, str]:
    checkout_source_directory = BIBLICUS_ROOT / "src"
    if not (checkout_source_directory / "biblicus").is_dir():
        return environment
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{checkout_source_directory}{os.pathsep}{existing_python_path}"
        if existing_python_path
        else str(checkout_source_directory)
    )
    return environment


def biblicus_corpus_catalog_path(corpus_directory: Path) -> Path:
    from biblicus.corpus import Corpus

    return Corpus.open(corpus_directory).catalog_path
