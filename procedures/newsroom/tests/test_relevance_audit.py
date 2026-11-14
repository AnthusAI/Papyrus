import json

import pytest

from papyrus_content.relevance_audit import audit_references, auroc, format_report, references_audit


def reference(n, probability, status="pending", **extra):
    return {"id": f"r{n}", "title": f"Reference {n}", "predictedAcceptProbability": probability, "curationStatus": status, "versionState": "current", **extra}


SYNTHETIC = [
    reference(1, 0.95, "accepted"), reference(2, 0.91, "accepted"), reference(3, 0.74, "accepted"),
    reference(4, 0.72, "pending"), reference(5, 0.64, "pending"), reference(6, 0.61, "archived"),
    reference(7, 0.78, "rejected", curationStatusReason="Off topic"), reference(8, 0.62, "rejected", curationReasonCode="duplicate"),
    {"id": "r9", "title": "Not scored", "curationStatus": "pending", "versionState": "current"},
    reference(10, 0.99, "accepted", versionState="superseded"),
]


def test_counts_medians_and_auroc():
    report = audit_references(SYNTHETIC)
    assert report["counts"] == {"references": 9, "withPrediction": 8, "accepted": 3, "rejected": 2, "untouched": 3}
    assert report["medianPredictedProbability"]["accepted"] == pytest.approx(0.91)
    assert report["medianPredictedProbability"]["untouched"] == pytest.approx(0.64)
    assert report["aurocAcceptedVsUntouched"] == pytest.approx(1.0)
    assert report["acceptShare"] == pytest.approx(3 / 8)


def test_bands_start_at_the_lowest_score_and_include_one():
    bands = audit_references(SYNTHETIC)["bands"]
    assert [band["from"] for band in bands] == [0.6, 0.7, 0.8, 0.9]
    assert [(b["delivered"], b["accepted"], b["rejected"]) for b in bands] == [(3, 0, 1), (3, 1, 1), (0, 0, 0), (2, 2, 0)]
    assert bands[2]["acceptShare"] is None
    top = audit_references([reference(1, 1.0, "accepted"), reference(2, 0.2, "pending")])["bands"]
    assert [band["from"] for band in top] == [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9] and top[-1]["accepted"] == 1


def test_rejects_list_prediction_and_reason_highest_first():
    rejects = audit_references(SYNTHETIC)["rejects"]
    assert [(r["id"], r["reason"]) for r in rejects] == [("r7", "Off topic"), ("r8", "duplicate")]


def test_auroc_ties_count_half_and_empty_groups_have_none():
    assert auroc([0.5], [0.5]) == 0.5
    assert auroc([], [0.5]) is None


def test_empty_site_reports_without_error():
    report = audit_references([])
    assert report["counts"]["withPrediction"] == 0 and report["bands"] == []
    assert "references\t0" in format_report(report)


class Client:
    def list_records(self, model):
        assert model == "Reference"
        return SYNTHETIC


def test_command_prints_text_or_json_and_only_reads(capsys):
    references_audit([], client=Client())
    assert "band\tdelivered\taccepted\trejected\taccept share" in capsys.readouterr().out
    references_audit(["--json"], client=Client())
    assert json.loads(capsys.readouterr().out)["counts"]["accepted"] == 3
