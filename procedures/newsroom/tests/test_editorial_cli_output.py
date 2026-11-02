"""check-version prints every finding; whole-story judgments say so; --version reports the installed distribution."""
import contextlib
import io
import json
from importlib.metadata import PackageNotFoundError
from unittest import mock

import papyrus
from papyrus_content import editorial_checks as editorial
from papyrus_content import editorial_commands as commands

FINDINGS = [
    {"id": "f-r", "policyId": "dp-measured", "severity": "warn", "status": "review", "probability": 0.53, "message": "Measured or modeled?", "excerpt": "Sales doubled."},
    {"id": "f-v", "policyId": "no-hype", "severity": "error", "status": "violation", "probability": 0.9, "message": "Avoid hype.", "excerpt": "game-changing"},
    {"id": "f-d", "policyId": "dp-doc", "severity": "warn", "status": "review", "message": "Applies to the whole story. Claims.", "excerpt": ""},
]


def run(flags):
    out = io.StringIO()
    with mock.patch.object(commands, "request_item_check", return_value={"itemId": "s-v1", "violations": 1, "reviews": 2}), \
            mock.patch.object(commands, "read_item_check_run", return_value={"findings": FINDINGS}), \
            contextlib.redirect_stdout(out):
        commands.editorial_check_version(["--item", "s-v1", *flags])
    return out.getvalue()


def test_text_output_keeps_summary_and_orders_violations_first():
    text = run([])
    assert text.splitlines()[0].startswith("editorial\tcheck\ts-v1\t1 violations\t2 for review")
    assert text.index("f-v") < text.index("f-r")
    assert "p=0.53" in text and "'Sales doubled.'" in text and "(none: the whole story)" in text


def test_json_output_has_full_findings():
    payload = json.loads(run(["--json"]))
    assert payload["findings"] == FINDINGS and payload["summary"]["reviews"] == 2


def test_whole_story_findings_are_marked_and_sentence_findings_are_not():
    result = {"findings": [
        {"segmentId": "doc", "excerpt": "", "message": "Claims."},
        {"segmentId": "s1", "excerpt": "Sales doubled.", "message": "Source?"},
    ]}
    editorial.mark_whole_story_findings(result)
    editorial.mark_whole_story_findings(result)  # idempotent
    assert result["findings"][0]["message"] == "Applies to the whole story. Claims."
    assert result["findings"][1]["message"] == "Source?"


def test_version_is_the_installed_distribution_with_a_source_fallback():
    assert papyrus.installed_version(lookup=lambda name: "5.70.0") == "5.70.0"

    def missing(name):
        raise PackageNotFoundError(name)

    assert papyrus.installed_version(lookup=missing) == papyrus.SOURCE_CHECKOUT_VERSION
