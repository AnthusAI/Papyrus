"""Forum-style titles and ledes for insight Messages."""

from __future__ import annotations

import re
from typing import Any

from .options import normalize_string

INSIGHT_FORUM_TITLE_MAX_LEN = 120
_GENERIC_HEADINGS = frozenset(
    {
        "sources",
        "references",
        "bibliography",
        "conclusion",
        "summary",
        "abstract",
        "introduction",
        "appendix",
    }
)


def derive_insight_forum_title(
    *,
    report_markdown: str = "",
    assignment_title: str = "",
    research_question: str = "",
    structured_summary: str = "",
) -> str:
    structured = normalize_string(structured_summary) or ""
    if structured and len(structured) <= INSIGHT_FORUM_TITLE_MAX_LEN:
        return structured

    question = normalize_string(research_question) or ""
    if question:
        return _truncate_insight_forum_title(question)

    heading = _first_markdown_h1(report_markdown)
    if heading and heading.lower() not in _GENERIC_HEADINGS:
        return _truncate_insight_forum_title(heading)

    assignment = normalize_string(assignment_title) or ""
    if assignment:
        return _truncate_insight_forum_title(assignment)

    report = str(report_markdown or "").strip()
    if report:
        without_heading = _strip_leading_markdown_heading(report)
        sentence = _first_sentence(without_heading)
        if sentence and len(sentence) <= INSIGHT_FORUM_TITLE_MAX_LEN:
            return sentence
        lede = without_heading.split("\n\n", 1)[0].strip()
        if lede and len(lede) <= INSIGHT_FORUM_TITLE_MAX_LEN:
            return lede

    return "Research insight"


def derive_insight_packet_lede(
    *,
    report_markdown: str = "",
    structured_summary: str = "",
) -> str:
    structured = normalize_string(structured_summary) or ""
    if structured:
        return structured[:500]
    report = str(report_markdown or "").strip()
    if not report:
        return "Research completed."
    body = _strip_leading_markdown_heading(report)
    paragraph = body.split("\n\n", 1)[0].strip() or body
    return paragraph[:500] if len(paragraph) > 500 else paragraph


def format_tavily_insight_message_body(
    *,
    report_markdown: str,
    research_question: str,
    assignment_title: str = "",
    tavily_request_id: str = "",
    tavily_model: str = "",
    tavily_status: str = "completed",
    source_count: int = 0,
    task_message_id: str = "",
) -> str:
    """Forum post body: Tavily task context, then the full report (not a summary)."""
    task_lines: list[str] = []
    query = normalize_string(research_question) or ""
    if query:
        task_lines.append(f"**Research query:** {query}")
    if assignment_title:
        task_lines.append(f"**Assignment:** {assignment_title}")
    if tavily_model:
        task_lines.append(f"**Tavily model:** {tavily_model}")
    if tavily_request_id:
        task_lines.append(f"**Tavily request ID:** `{tavily_request_id}`")
    if tavily_status:
        task_lines.append(f"**Status:** {tavily_status}")
    if source_count:
        task_lines.append(f"**Sources returned:** {source_count}")
    if task_message_id:
        task_lines.append(f"**Task message:** `{task_message_id}`")

    report = str(report_markdown or "").strip()
    sections: list[str] = []
    if task_lines:
        sections.append("## Research task\n\n" + "\n".join(task_lines))
    if report:
        if report.startswith("## Research task"):
            return report
        sections.append("## Report\n\n" + report)
    return "\n\n".join(sections).strip() or report or "Tavily deep research completed."


def extract_tavily_report_markdown(body_text: str) -> str:
    """Pull report section from a formatted Tavily insight body, if present."""
    text = str(body_text or "").strip()
    marker = "## Report\n\n"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    if text.startswith("## Research task"):
        return ""
    return text


def tavily_insight_body_needs_task_section(body_text: str) -> bool:
    return "## Research task" not in str(body_text or "")


def insight_summary_needs_title_repair(summary: str, body_text: str) -> bool:
    title = normalize_string(summary) or ""
    body = str(body_text or "").strip()
    if not title:
        return True
    if len(title) > INSIGHT_FORUM_TITLE_MAX_LEN:
        return True
    if body and (body.startswith(title) or title.startswith(body[: min(len(body), 80)])):
        return True
    return False


def _first_markdown_h1(markdown: str) -> str:
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        match = re.match(r"^# ([^#].+)$", stripped)
        if match:
            return match.group(1).strip()
    return ""


def _strip_leading_markdown_heading(markdown: str) -> str:
    lines = str(markdown or "").splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if re.match(r"^#{1,6}\s+", stripped):
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            continue
        break
    return "\n".join(lines[index:]).strip()


def _first_sentence(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    if not normalized:
        return ""
    for marker in (". ", "? ", "! ", ".\n", "?\n", "!\n"):
        position = normalized.find(marker)
        if position > 0:
            candidate = normalized[: position + 1].strip()
            if len(candidate) <= INSIGHT_FORUM_TITLE_MAX_LEN:
                return candidate
    return normalized if len(normalized) <= INSIGHT_FORUM_TITLE_MAX_LEN else ""


def _truncate_insight_forum_title(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return "Research insight"
    if len(text) <= INSIGHT_FORUM_TITLE_MAX_LEN:
        return text
    shortened = text[: INSIGHT_FORUM_TITLE_MAX_LEN - 1].rsplit(" ", 1)[0].strip()
    return shortened or text[:INSIGHT_FORUM_TITLE_MAX_LEN]
