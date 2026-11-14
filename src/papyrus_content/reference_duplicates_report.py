"""Read-only report of duplicate References: `papyrus references duplicates`.

Groups the publication's current References by identity key (reference_identity.py) and counts same-title groups as candidates only.
It lists what it needs and writes nothing: no record, no attachment, no relation.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .reference_identity import identity_groups, identity_keys, is_current, title_candidate_key

KINDS = ("url", "arxiv", "doi", "text")
CAPTURED_TEXT_ATTACHMENT = "extracted_text"


def attach_captured_text_hashes(references: list[dict[str, Any]], attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copies of the References that carry ``capturedTextSha256`` from their extracted-text attachment (matched by lineage)."""
    by_lineage = {a.get("referenceLineageId"): a.get("sha256") for a in attachments
                  if a.get("role") == CAPTURED_TEXT_ATTACHMENT and a.get("sha256") and a.get("referenceLineageId")}
    return [{**row, "capturedTextSha256": by_lineage[row["lineageId"]]} if row.get("lineageId") in by_lineage else row for row in references]


def _member(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row.get("id"), "corpusId": row.get("corpusId"), "status": row.get("curationStatus") or "pending", "createdAt": row.get("createdAt")}


def _extra_rows(groups: list[dict[str, Any]]) -> int:
    return sum(len(group["members"]) - 1 for group in groups)


def build_duplicates_report(references: list[dict[str, Any]], attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The report as plain data. ``attachments`` (optional) supplies captured-text hashes for the `text` key."""
    current = [row for row in references if is_current(row)]
    if attachments is not None:
        current = attach_captured_text_hashes(current, attachments)
    joined = identity_groups(current)
    by_kind = {}
    for kind in KINDS:
        groups = identity_groups(current, kinds=[kind])
        by_kind[kind] = {"groups": len(groups), "extraRows": _extra_rows(groups)}
    titled: dict[str, list[dict[str, Any]]] = {}
    for row in current:
        key = title_candidate_key(row)
        if key:
            titled.setdefault(key, []).append(row)
    group_of: dict[str, int] = {str(member.get("id")): number for number, group in enumerate(joined) for member in group["members"]}
    title_groups = [rows for rows in titled.values() if len(rows) > 1]
    different_documents = [rows for rows in title_groups
                           if len({group_of.get(str(row.get("id")), f"alone-{row.get('id')}") for row in rows}) > 1]
    return {
        "references": len(current),
        "corpora": dict(sorted(Counter(str(row.get("corpusId")) for row in current).items())),
        "statuses": dict(sorted(Counter(str(row.get("curationStatus") or "pending") for row in current).items())),
        "withoutIdentityKey": sum(1 for row in current if not identity_keys(row)),
        "withCapturedTextHash": sum(1 for row in current if any(key.startswith("text:") for key in identity_keys(row))),
        "identity": {"groups": len(joined), "extraRows": _extra_rows(joined), "byKind": by_kind,
                     "groupsAcrossCorpora": sum(1 for group in joined if len({m.get("corpusId") for m in group["members"]}) > 1),
                     "groupsWithDifferentStatuses": sum(1 for group in joined if len({m.get("curationStatus") or "pending" for m in group["members"]}) > 1),
                     "groupsHoldingAccepted": sum(1 for group in joined if any(m.get("curationStatus") == "accepted" for m in group["members"]))},
        "sameTitleCandidates": {"note": "candidates only: the same title is not the same document",
                                "groups": len(title_groups), "rows": sum(len(rows) for rows in title_groups),
                                "groupsNotAlreadyOneIdentity": len(different_documents),
                                "rowsInThoseGroups": sum(len(rows) for rows in different_documents)},
        "groups": [{"keys": group["keys"], "members": [_member(m) for m in group["members"]]} for group in joined],
    }


def render_text(report: dict[str, Any], *, groups: bool = False) -> str:
    identity, titles = report["identity"], report["sameTitleCandidates"]
    lines = [f"references\t{report['references']}", f"corpora\t{len(report['corpora'])}",
             *(f"status\t{name}\t{count}" for name, count in report["statuses"].items()),
             f"without-identity-key\t{report['withoutIdentityKey']}",
             f"with-captured-text-hash\t{report['withCapturedTextHash']}",
             f"identity-groups\t{identity['groups']}\textra-rows\t{identity['extraRows']}",
             *(f"identity-{kind}\tgroups={found['groups']}\textra-rows={found['extraRows']}" for kind, found in identity["byKind"].items()),
             f"identity-groups-across-corpora\t{identity['groupsAcrossCorpora']}",
             f"identity-groups-with-different-statuses\t{identity['groupsWithDifferentStatuses']}",
             f"identity-groups-holding-accepted\t{identity['groupsHoldingAccepted']}",
             f"same-title-candidates\tgroups={titles['groups']}\trows={titles['rows']}\t(candidates, not duplicates)",
             f"same-title-candidates-not-already-one-identity\tgroups={titles['groupsNotAlreadyOneIdentity']}\trows={titles['rowsInThoseGroups']}"]
    if groups:
        for number, group in enumerate(report["groups"], start=1):
            lines.append(f"group\t{number}\t{','.join(group['keys'])}")
            lines.extend(f"member\t{m['id']}\t{m['corpusId']}\t{m['status']}\t{m['createdAt']}" for m in group["members"])
    return "\n".join(lines)
