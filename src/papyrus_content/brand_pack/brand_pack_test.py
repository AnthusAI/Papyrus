"""BrandPack v1 schema and validator, driven by the shared vectors in scripts/fixtures/brand-pack-vectors.json (the TypeScript twin reads the same file)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from papyrus_content.brand_pack import POLICY, SCHEMA, validate_brand_pack
from papyrus_content.brand_pack.validate import contrast_ratio

VECTORS = json.loads((Path(__file__).resolve().parents[3] / "scripts" / "fixtures" / "brand-pack-vectors.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", VECTORS, ids=[case["name"] for case in VECTORS])
def test_vector(case):
    errors = validate_brand_pack(case["pack"])
    assert len(errors) == len(case["errors"]), errors
    for expected in case["errors"]:
        assert any(expected in error for error in errors), (expected, errors)


def test_the_vectors_cover_valid_and_refused_packs():
    assert any(not case["errors"] for case in VECTORS) and any(case["errors"] for case in VECTORS)


def test_contrast_matches_the_wcag_reference_values():
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)
    assert contrast_ratio("#767676", "#FFFFFF") == pytest.approx(4.54, abs=0.01)


def test_every_policy_pair_names_roles_in_the_schema():
    roles = set(SCHEMA["$defs"]["theme"]["properties"])
    for pair in POLICY["textPairs"] + POLICY["lightnessPairs"]:
        assert {pair["foreground"], pair["background"]} <= roles


def test_every_role_is_covered_by_a_policy_pair():
    roles = set(SCHEMA["$defs"]["theme"]["properties"])
    covered = {r for pair in POLICY["textPairs"] + POLICY["lightnessPairs"] for r in (pair["foreground"], pair["background"])}
    assert covered == roles


def test_the_allow_list_has_unique_families():
    families = [font["family"] for font in POLICY["fonts"]]
    assert len(families) == len(set(families))
