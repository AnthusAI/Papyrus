import humanus
import pytest

from papyrus_content.localize.checks import reconsider_name_findings
from papyrus_content.translation_glossary import Glossary, starter_glossary


def _parity_findings(source: str, target: str, glossary: Glossary) -> list[dict]:
    """Humanus's parity lane on one block, then Papyrus's reconsideration of its name findings: what a translation is held on, with no model."""
    request = {"schemaVersion": 1, "content": {"text": target, "format": "markdown", "language": glossary.language},
               "source": {"text": source, "format": "markdown", "language": "en"},
               "glossary": glossary.humanus(glossary.entries_in([source])), "pack": humanus.builtin_pack("translation-faithfulness"),
               "options": {"lanes": {"rules": False, "classifier": False, "parity": True, "judge": False}}}
    raw = humanus.check(request, decision_model=None)["findings"]
    return reconsider_name_findings(raw, target=target, target_language=glossary.language, glossary=glossary)


def _name_errors(findings: list[dict]) -> list[str]:
    return [f["source"]["excerpt"] for f in findings if f["policyId"] == "names" and f["severity"] == "error"]


@pytest.mark.parametrize("language, source, target", [
    ("es-419", "Schools are buying AIs for tutoring.", "Las escuelas compran IA para dar tutorías."),
    ("es-419", "A U.S-based firm said so.", "Una empresa con sede en EE. UU. lo dijo."),
])
def test_a_name_the_glossary_renders_is_kept_by_its_approved_form(language, source, target):
    findings = _parity_findings(source, target, starter_glossary(language))
    assert [f for f in findings if f["policyId"] in ("names", "names-adapted")] == [], findings


def test_a_glossary_name_whose_approved_form_is_missing_is_still_reported():
    findings = _parity_findings("Schools are buying AIs for tutoring.", "Las escuelas compran programas para dar tutorías.", starter_glossary("es-419"))
    assert _name_errors(findings) == ["AIs"], findings


@pytest.mark.parametrize("language, target", [
    ("es-419", "El proyecto contó con el apoyo del representante Nick LaLota."),
    ("zh-Hans", "该法案得到了众议员 Nick LaLota 的支持。"),
])
def test_a_translated_title_before_a_name_does_not_lose_the_name(language, target):
    findings = _parity_findings("The bill was backed by Representative Nick LaLota.", target, starter_glossary(language))
    assert _name_errors(findings) == [], findings


def test_a_name_lost_with_its_title_is_still_an_error():
    findings = _parity_findings("The bill was backed by Representative Nick LaLota.", "El proyecto contó con el apoyo del representante.", starter_glossary("es-419"))
    assert _name_errors(findings) == ["Representative Nick LaLota"], findings


@pytest.mark.parametrize("language, source, target", [
    ("es-419", "The UN said the ID system failed on TV.", "La ONU dijo en televisión que el sistema de identificación falló."),
    ("es-419", "By the 1970s, IDs were common.", "En los años setenta, los documentos de identidad eran comunes."),
    ("zh-Hans", "The UN said the ID system failed on TV.", "联合国在电视上说身份系统失败了。"),
])
def test_an_initialism_a_language_writes_its_own_way_is_advice_not_an_error(language, source, target):
    findings = _parity_findings(source, target, starter_glossary(language))
    assert _name_errors(findings) == [], findings
    assert {f["policyId"] for f in findings if f["source"]["excerpt"] in ("UN", "ID", "IDs", "TV")} <= {"names-adapted"}, findings


def test_a_lost_brand_name_still_holds_a_translation():
    findings = _parity_findings("Researchers at OpenAI tested the agent.", "Los investigadores probaron al agente.", starter_glossary("es-419"))
    assert _name_errors(findings) == ["OpenAI"], findings


def test_findings_of_other_policies_pass_through_unchanged():
    raw = [{"policyId": "numbers", "severity": "error", "message": "m", "source": {"excerpt": "42"}}]
    assert reconsider_name_findings(raw, target="x", target_language="es-419", glossary=Glossary.of("es-419", [])) == raw
