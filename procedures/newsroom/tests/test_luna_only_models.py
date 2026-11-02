"""Ryan's rule (2026-11-02): every LLM call uses ``gpt-6-luna``.

Fails when product code names any other OpenAI model identifier. Speech models are not LLM calls and are named in
``ALLOWED_MODEL_IDENTIFIERS``; a file that must name other models on purpose (a vendor comparison) is listed in
``VENDOR_COMPARISON_PATHS`` with its reason. Tests, docs, publication content and fixtures are not product code.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

LUNA = "gpt-6-luna"

MODEL_IDENTIFIER = re.compile(r"(?<![\w.-])(gpt-[0-9][\w.-]*|chatgpt-[\w.-]+|o[1-9]-(?:mini|pro|preview|deep-research)[\w.-]*)")

ALLOWED_MODEL_IDENTIFIERS = {
    LUNA: "the one language model every LLM call uses",
    "gpt-4o-mini-tts": "speech synthesis (video narration voices), not an LLM call",
}

VENDOR_COMPARISON_PATHS: dict[str, str] = {}

SCANNED_SUFFIXES = {".py", ".ts", ".tsx", ".mjs", ".cjs", ".js", ".tac", ".rs", ".sh", ".yml", ".yaml", ".json", ".toml"}

NOT_PRODUCT_CODE = tuple(
    re.compile(pattern)
    for pattern in (
        r"^docs/", r"^project/", r"^publications/", r"^public/", r"^pods/", r"^corpora/", r"^skills/", r"^\.agents/",
        r"^features(_backend)?/", r"^procedures/guards/", r"^marketing/",
        r"(^|/)tests?/", r"(^|/)__tests__/", r"_test\.py$", r"(^|/)test[-_][^/]*$", r"\.test\.[a-z]+$", r"-bdd-harness\.ts$",
        r"(^|/)(package-lock\.json|poetry\.lock|Cargo\.lock|amplify_outputs\.json|tsconfig\.tsbuildinfo)$",
        r"\.template\.json$", r"(^|/)node_modules/", r"(^|/)cdk\.context\.json$",
    )
)


def other_models(text: str) -> list[str]:
    return sorted({found for found in MODEL_IDENTIFIER.findall(text) if found not in ALLOWED_MODEL_IDENTIFIERS and not found.startswith(LUNA + "-")})


def product_files() -> list[Path]:
    listed = subprocess.run(["git", "ls-files"], cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    return [
        REPOSITORY_ROOT / relative
        for relative in listed
        if Path(relative).suffix in SCANNED_SUFFIXES
        and not any(pattern.search(relative) for pattern in NOT_PRODUCT_CODE)
        and relative not in VENDOR_COMPARISON_PATHS
    ]


def test_the_scan_names_a_retired_model_and_lets_luna_and_speech_through():
    assert other_models('model="gpt-5.4-mini" and "gpt-5.4-nano" and "gpt-4o"') == ["gpt-4o", "gpt-5.4-mini", "gpt-5.4-nano"]
    assert other_models('model: o3-mini, chatgpt-4o-latest') == ["chatgpt-4o-latest", "o3-mini"]
    assert other_models('"gpt-6-luna" "gpt-6-luna-2026-09-01" "gpt-4o-mini-tts" ChatGPT GPT-4') == []


def test_product_code_names_no_openai_model_but_luna():
    found = {}
    for path in product_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        models = other_models(text)
        if models:
            found[str(path.relative_to(REPOSITORY_ROOT))] = models
    assert not found, (
        "Every LLM call uses gpt-6-luna. Move these to it (speech models go in ALLOWED_MODEL_IDENTIFIERS, a deliberate "
        f"vendor comparison in VENDOR_COMPARISON_PATHS with its reason): {found}"
    )
