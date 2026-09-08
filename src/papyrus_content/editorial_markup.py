from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from xml.dom import minidom

from .editorial_diagnosis_schema import FINDING_ARRAY_KEYS

EDITORIAL_ANNOTATION_NS = "https://papyrus.anth.us/editorial-annotation/v1"
ANNOTATION_SCHEMA_VERSION = 1


def collect_findings_from_diagnosis(diagnosis: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for key in FINDING_ARRAY_KEYS:
        for finding in diagnosis.get(key, []):
            if isinstance(finding, dict):
                findings.append(dict(finding))
    for group in diagnosis.get("repetition_groups", []):
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id") or "")
        for member in group.get("members", []):
            if not isinstance(member, dict):
                continue
            enriched = dict(member)
            if group_id:
                enriched["group_id"] = group_id
            findings.append(enriched)
    return sorted(findings, key=lambda item: (item["span"]["start"], item["span"]["end"], item["id"]))


def _markus_attr(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()
    return f'"{escaped}"'


def render_markus_finding_block(finding: dict[str, Any], *, excerpt: str) -> str:
    attrs = [
        f"id={_markus_attr(str(finding['id']))}",
        f"kind={_markus_attr(str(finding['kind']))}",
    ]
    rationale = str(finding.get("rationale") or "").strip()
    if rationale:
        attrs.append(f"rationale={_markus_attr(rationale)}")
    group_id = str(finding.get("group_id") or "").strip()
    if group_id:
        attrs.append(f"group={_markus_attr(group_id)}")
    decision = str(finding.get("decision") or "").strip()
    if decision:
        attrs.append(f"decision={_markus_attr(decision)}")
    attr_text = " ".join(attrs)
    body = excerpt.strip()
    if not body:
        return f"::editorial-finding{{{attr_text}}}\n"
    return f":::editorial-finding{{{attr_text}}}\n{body}\n:::\n"


def _is_document_level(finding: dict[str, Any], draft_len: int) -> bool:
    span = finding.get("span") or {}
    start = int(span.get("start", -1))
    end = int(span.get("end", -1))
    return start == 0 and end >= draft_len


def inject_markus_findings(draft_text: str, findings: list[dict[str, Any]]) -> str:
    draft_len = len(draft_text)
    document_level: list[dict[str, Any]] = []
    span_level: list[dict[str, Any]] = []
    for finding in findings:
        if _is_document_level(finding, draft_len):
            document_level.append(finding)
        else:
            span_level.append(finding)

    prefix_blocks = [
        render_markus_finding_block(finding, excerpt="") for finding in document_level
    ]
    prefix = "".join(prefix_blocks)

    text = draft_text
    wrapped: list[tuple[int, int]] = []
    for finding in sorted(span_level, key=lambda item: item["span"]["start"], reverse=True):
        span = finding["span"]
        start = int(span["start"])
        end = int(span["end"])
        if start < 0 or end > len(text) or start >= end:
            continue
        if any(start < existing_end and end > existing_start for existing_start, existing_end in wrapped):
            continue
        excerpt = text[start:end]
        block = render_markus_finding_block(finding, excerpt=excerpt)
        text = text[:start] + block + text[end:]
        wrapped.append((start, start + len(block)))
    return prefix + text


def render_annotated_markus(draft_text: str, diagnosis: dict[str, Any]) -> str:
    findings = collect_findings_from_diagnosis(diagnosis)
    return inject_markus_findings(draft_text, findings)


def render_annotated_xml(draft_text: str, diagnosis: dict[str, Any]) -> str:
    root = ET.Element(
        "editorialAnnotation",
        {
            "xmlns": EDITORIAL_ANNOTATION_NS,
            "schemaVersion": str(ANNOTATION_SCHEMA_VERSION),
        },
    )

    density = diagnosis.get("density")
    if isinstance(density, dict):
        density_el = ET.SubElement(root, "density")
        for key in ("wordCount", "sentenceCount", "lexicalDensity", "gzipRatio"):
            if key in density:
                child = ET.SubElement(density_el, key)
                child.text = str(density[key])

    findings_el = ET.SubElement(root, "findings")
    for finding in collect_findings_from_diagnosis(diagnosis):
        attrs = {
            "id": str(finding["id"]),
            "kind": str(finding["kind"]),
            "start": str(finding["span"]["start"]),
            "end": str(finding["span"]["end"]),
        }
        group_id = str(finding.get("group_id") or "").strip()
        if group_id:
            attrs["group"] = group_id
        finding_el = ET.SubElement(findings_el, "finding", attrs)
        rationale_el = ET.SubElement(finding_el, "rationale")
        rationale_el.text = str(finding.get("rationale") or "")
        excerpt_el = ET.SubElement(finding_el, "excerpt")
        excerpt_el.text = str(finding.get("excerpt") or "")

    markus_el = ET.SubElement(root, "markusAnnotated")
    markus_el.text = render_annotated_markus(draft_text, diagnosis)

    source_el = ET.SubElement(root, "source")
    source_el.text = draft_text

    xml_bytes = ET.tostring(root, encoding="utf-8")
    parsed = minidom.parseString(xml_bytes)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
