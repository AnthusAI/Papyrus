"""``papyrus references audit``: the relevance model's predictions against editors' decisions, read-only.

Every Reference the relevance Cyclotron scored carries ``predictedAcceptProbability``. Editors accept or reject
References. This command lines the two up: how the scores of accepted References compare with those of References no
editor has touched, how often an accept follows each band of score, and which rejected References the model had
scored. It reads References and writes nothing.
"""
from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from statistics import median
from typing import Any

from .graphql_authoring import create_authoring_client
from .options import parse_boolean_option, parse_options


def decision_of(reference: dict[str, Any]) -> str:
    """``accepted``, ``rejected`` or ``untouched`` (pending, or any status that is not an editor's accept or reject)."""
    status = reference.get("curationStatus")
    return status if status in ("accepted", "rejected") else "untouched"


def auroc(positives: list[float], negatives: list[float]) -> float | None:
    """The chance a random accepted score is above a random untouched one (ties count half); None without both groups."""
    if not positives or not negatives:
        return None
    ordered = sorted(negatives)
    wins = sum(bisect_left(ordered, score) + 0.5 * (bisect_right(ordered, score) - bisect_left(ordered, score)) for score in positives)
    return wins / (len(positives) * len(negatives))


def _share(accepted: int, delivered: int) -> float | None:
    return accepted / delivered if delivered else None


def audit_references(references: list[dict[str, Any]]) -> dict[str, Any]:
    """The audit of a site's References (current versions only), as a JSON-ready dict."""
    current = [row for row in references if row.get("versionState") in (None, "current")]
    scored = [row for row in current if row.get("predictedAcceptProbability") is not None]
    by_decision: dict[str, list[dict[str, Any]]] = {"accepted": [], "rejected": [], "untouched": []}
    for row in scored:
        by_decision[decision_of(row)].append(row)
    scores = {name: [float(row["predictedAcceptProbability"]) for row in rows] for name, rows in by_decision.items()}
    report: dict[str, Any] = {
        "counts": {
            "references": len(current),
            "withPrediction": len(scored),
            "accepted": len(by_decision["accepted"]),
            "rejected": len(by_decision["rejected"]),
            "untouched": len(by_decision["untouched"]),
        },
        "medianPredictedProbability": {name: (median(values) if values else None) for name, values in scores.items()},
        "aurocAcceptedVsUntouched": auroc(scores["accepted"], scores["untouched"]),
        "acceptShare": _share(len(by_decision["accepted"]), len(scored)),
        "bands": [],
        "rejects": [],
    }
    if scored:
        # Tenths of a probability, taken from the lowest score seen up to 1.0 (1.0 belongs to the top band).
        tenth = lambda value: min(int(float(value) * 10 + 1e-9), 9)  # noqa: E731
        for low in range(tenth(min(float(row["predictedAcceptProbability"]) for row in scored)), 10):
            rows = [row for row in scored if tenth(row["predictedAcceptProbability"]) == low]
            accepted = sum(decision_of(row) == "accepted" for row in rows)
            report["bands"].append({
                "from": low / 10, "to": (low + 1) / 10, "delivered": len(rows), "accepted": accepted,
                "rejected": sum(decision_of(row) == "rejected" for row in rows), "acceptShare": _share(accepted, len(rows)),
            })
    for row in sorted(by_decision["rejected"], key=lambda item: -float(item["predictedAcceptProbability"])):
        report["rejects"].append({
            "id": row.get("id"), "title": row.get("title"), "predictedAcceptProbability": float(row["predictedAcceptProbability"]),
            "reason": row.get("curationStatusReason") or row.get("curationReasonCode"),
        })
    return report


def _fmt(value: float | None, pattern: str = "{:.2f}") -> str:
    return "-" if value is None else pattern.format(value)


def format_report(report: dict[str, Any]) -> str:
    counts, medians = report["counts"], report["medianPredictedProbability"]
    lines = [
        f"references\t{counts['references']}\twith prediction\t{counts['withPrediction']}",
        f"accepted\t{counts['accepted']}\trejected\t{counts['rejected']}\tuntouched\t{counts['untouched']}",
        f"median predicted probability\taccepted {_fmt(medians['accepted'])}\tuntouched {_fmt(medians['untouched'])}\trejected {_fmt(medians['rejected'])}",
        f"AUROC accepted vs untouched\t{_fmt(report['aurocAcceptedVsUntouched'])}",
        f"accept share of predicted references\t{_fmt(report['acceptShare'], '{:.0%}')}",
        "",
        "band\tdelivered\taccepted\trejected\taccept share",
    ]
    for band in report["bands"]:
        lines.append(f"{band['from']:.1f}-{band['to']:.1f}\t{band['delivered']}\t{band['accepted']}\t{band['rejected']}\t{_fmt(band['acceptShare'], '{:.0%}')}")
    if report["rejects"]:
        lines += ["", "rejected references with a prediction"]
        lines += [f"{row['predictedAcceptProbability']:.2f}\t{(row['title'] or row['id'] or '')[:70]}\twhy: {row['reason'] or 'none given'}" for row in report["rejects"]]
    return "\n".join(lines)


def references_audit(flags: list[str], *, client: Any = None) -> None:
    options = parse_options(flags)
    as_json = parse_boolean_option(options.get("json"), False, "--json")
    if client is None:
        client, _ = create_authoring_client()
    report = audit_references(client.list_records("Reference"))
    print(json.dumps(report, indent=2) if as_json else format_report(report))
