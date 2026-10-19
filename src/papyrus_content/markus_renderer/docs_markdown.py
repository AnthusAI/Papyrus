"""Rewrite other Markdown dialects into Markus directives on staged copies of documentation pages.

MkDocs admonitions, tabbed blocks, collapsible blocks, GitHub alerts, bold-label
quotes, HTML ``details`` blocks and HTML ``img`` tags have Markus equivalents
(``callout``, ``tabs``, ``details`` and Markdown images). Source files are never
edited: the builder runs these steps over its staged copies only. Anything inside
a fenced code block is left alone.
"""

from __future__ import annotations

import re

FENCE_PATTERN = re.compile(r"^\s*(`{3,}|~{3,})")
ADMONITION_PATTERN = re.compile(
    r"^(?P<marker>!!!|\?\?\?\+?)[ \t]+(?P<kind>[\w-]+)(?P<modifiers>(?:[ \t]+[\w.-]+)*)"
    r'(?:[ \t]+"(?P<title>[^"]*)")?[ \t]*$'
)
TAB_PATTERN = re.compile(r'^===\+?[ \t]+"(?P<label>[^"]*)"[ \t]*$')
GITHUB_ALERT_PATTERN = re.compile(r"^\[!(?P<kind>NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*$", re.IGNORECASE)
BOLD_LABEL_PATTERN = re.compile(
    r"^\*\*(?P<kind>Note|Tip|Hint|Warning|Important|Caution|Danger)[ \t]*[:.]?\*\*[ \t]*:?[ \t]*(?P<rest>.*)$",
    re.IGNORECASE,
)
DETAILS_OPEN_PATTERN = re.compile(r"^<details(?P<open>\s+open)?\s*>\s*(?P<rest>.*)$", re.IGNORECASE)
SUMMARY_PATTERN = re.compile(r"<summary>(?P<summary>.*?)</summary>\s*(?P<rest>.*)$", re.IGNORECASE)
IMAGE_TAG_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
INLINE_CODE_PATTERN = re.compile(r"(`+[^`]*`+)")

CALLOUT_KIND_FOR_ADMONITION = {
    "note": "note",
    "info": "note",
    "abstract": "note",
    "summary": "note",
    "tldr": "note",
    "todo": "note",
    "example": "note",
    "quote": "note",
    "cite": "note",
    "question": "note",
    "faq": "note",
    "important": "note",
    "tip": "tip",
    "hint": "tip",
    "success": "tip",
    "check": "tip",
    "done": "tip",
    "warning": "warning",
    "attention": "warning",
    "help": "warning",
    "danger": "caution",
    "error": "caution",
    "failure": "caution",
    "fail": "caution",
    "missing": "caution",
    "bug": "caution",
    "caution": "caution",
}
BODY_INDENT = "    "


def convert_markdown_dialects(page_text: str) -> str:
    """Apply every dialect conversion to a page, leaving fenced code blocks untouched."""
    lines = page_text.split("\n")
    return "\n".join(convert_lines(lines))


def convert_lines(lines: list[str]) -> list[str]:
    converted: list[str] = []
    open_fence: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        fence_match = FENCE_PATTERN.match(line)
        if open_fence is not None:
            converted.append(line)
            if fence_match and line.strip().startswith(open_fence) and set(line.strip()) <= {open_fence[0]}:
                open_fence = None
            index += 1
            continue
        if fence_match:
            open_fence = fence_match.group(1)
            converted.append(line)
            index += 1
            continue
        admonition = ADMONITION_PATTERN.match(line)
        if admonition:
            body, index = take_indented_body(lines, index + 1)
            converted.extend(admonition_directive(admonition, body))
            continue
        if TAB_PATTERN.match(line):
            tabs, index = take_tab_group(lines, index)
            converted.extend(tabs_directive(tabs))
            continue
        if line.startswith(">"):
            quote_end = index
            while quote_end < len(lines) and lines[quote_end].startswith(">"):
                quote_end += 1
            converted.extend(convert_quote(lines[index:quote_end]))
            index = quote_end
            continue
        details = DETAILS_OPEN_PATTERN.match(line.strip()) if not line.startswith((" ", "\t")) else None
        if details:
            block, index = take_details_block(lines, index)
            if block is not None:
                converted.extend(details_directive(block))
                continue
        converted.append(convert_image_tags(line))
        index += 1
    return converted


def take_indented_body(lines: list[str], start: int) -> tuple[list[str], int]:
    """Collect the indented lines after a block marker, dedented, trimming trailing blanks."""
    body: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if line.strip() == "":
            body.append("")
        elif line.startswith(BODY_INDENT):
            body.append(line[len(BODY_INDENT) :])
        elif line.startswith("\t"):
            body.append(line[1:])
        else:
            break
        index += 1
    while body and body[-1] == "":
        body.pop()
        index -= 1
    return body, index


def directive_fence(converted_body: list[str], minimum: int = 3) -> str:
    deepest = 0
    for line in converted_body:
        match = re.match(r"^\s*(:{3,})", line)
        if match:
            deepest = max(deepest, len(match.group(1)))
    return ":" * max(minimum, deepest + 1)


def attribute_value(text: str) -> str:
    return text.replace('"', "'").replace("}", ")").replace("{", "(").strip()


def admonition_directive(match: re.Match[str], body: list[str]) -> list[str]:
    converted_body = convert_lines(body)
    kind_name = match.group("kind").lower()
    title = match.group("title")
    collapsible = match.group("marker").startswith("???")
    fence = directive_fence(converted_body)
    if collapsible:
        summary = attribute_value(title if title else kind_name.capitalize())
        opened = " open=true" if match.group("marker") == "???+" else ""
        head = f'{fence}details{{summary="{summary}"{opened}}}'
    else:
        callout_kind = CALLOUT_KIND_FOR_ADMONITION.get(kind_name, "note")
        title_part = f' title="{attribute_value(title)}"' if title else ""
        head = f'{fence}callout{{kind="{callout_kind}"{title_part}}}'
    return [head, *converted_body, fence, ""]


def take_tab_group(lines: list[str], start: int) -> tuple[list[tuple[str, list[str]]], int]:
    tabs: list[tuple[str, list[str]]] = []
    index = start
    while index < len(lines):
        header = TAB_PATTERN.match(lines[index])
        if not header:
            break
        body, next_index = take_indented_body(lines, index + 1)
        tabs.append((header.group("label"), body))
        index = next_index
        probe = index
        while probe < len(lines) and lines[probe].strip() == "":
            probe += 1
        if probe < len(lines) and TAB_PATTERN.match(lines[probe]):
            index = probe
        else:
            break
    return tabs, index


def tabs_directive(tabs: list[tuple[str, list[str]]]) -> list[str]:
    converted_tabs = [(label, convert_lines(body)) for label, body in tabs]
    tab_fence = directive_fence([line for _, body in converted_tabs for line in body])
    tabs_fence = ":" * (len(tab_fence) + 1)
    output = [tabs_fence + "tabs"]
    for label, body in converted_tabs:
        output.extend([f'{tab_fence}tab{{label="{attribute_value(label)}"}}', *body, tab_fence])
    output.extend([tabs_fence, ""])
    return output


def convert_quote(quote_lines: list[str]) -> list[str]:
    content = [re.sub(r"^> ?", "", line) for line in quote_lines]
    first = content[0].strip()
    alert = GITHUB_ALERT_PATTERN.match(first)
    labelled = BOLD_LABEL_PATTERN.match(first)
    if alert:
        kind_name = alert.group("kind").lower()
        body = content[1:]
    elif labelled and (labelled.group("kind") and first.startswith("**")):
        kind_name = labelled.group("kind").lower()
        body = ([labelled.group("rest")] if labelled.group("rest") else []) + content[1:]
    else:
        return list(quote_lines)
    callout_kind = CALLOUT_KIND_FOR_ADMONITION.get(kind_name, "note")
    converted_body = convert_lines(body)
    fence = directive_fence(converted_body)
    return [f'{fence}callout{{kind="{callout_kind}"}}', *converted_body, fence, ""]


def take_details_block(lines: list[str], start: int) -> tuple[dict | None, int]:
    opening = DETAILS_OPEN_PATTERN.match(lines[start].strip())
    assert opening is not None
    inner: list[str] = []
    if opening.group("rest"):
        inner.append(opening.group("rest"))
    index = start + 1
    while index < len(lines):
        if lines[index].strip().lower().endswith("</details>"):
            tail = re.sub(r"</details>\s*$", "", lines[index].strip(), flags=re.IGNORECASE)
            if tail:
                inner.append(tail)
            break
        inner.append(lines[index])
        index += 1
    else:
        return None, start
    summary = "Details"
    for position, line in enumerate(inner):
        found = SUMMARY_PATTERN.search(line.strip())
        if found:
            summary = re.sub(r"<[^>]+>", "", found.group("summary")).strip() or summary
            inner[position] = found.group("rest")
            break
    body = [line for line in inner if not re.fullmatch(r"\s*</?summary>\s*", line)]
    return {"summary": summary, "open": bool(opening.group("open")), "body": body}, index + 1


def details_directive(block: dict) -> list[str]:
    converted_body = convert_lines(block["body"])
    while converted_body and converted_body[0].strip() == "":
        converted_body.pop(0)
    fence = directive_fence(converted_body)
    opened = " open=true" if block["open"] else ""
    return [f'{fence}details{{summary="{attribute_value(block["summary"])}"{opened}}}', *converted_body, fence, ""]


def convert_image_tags(line: str) -> str:
    """Turn ``<img src alt>`` tags (outside inline code) into Markdown images."""
    if "<img" not in line.lower():
        return line
    pieces = INLINE_CODE_PATTERN.split(line)
    for position in range(0, len(pieces), 2):
        pieces[position] = IMAGE_TAG_PATTERN.sub(image_tag_to_markdown, pieces[position])
    return "".join(pieces)


def image_tag_to_markdown(match: re.Match[str]) -> str:
    tag = match.group(0)
    source = re.search(r'\bsrc\s*=\s*"([^"]*)"|\bsrc\s*=\s*\'([^\']*)\'', tag)
    if not source:
        return tag
    alternative = re.search(r'\balt\s*=\s*"([^"]*)"|\balt\s*=\s*\'([^\']*)\'', tag)
    alt_text = (alternative.group(1) or alternative.group(2) or "") if alternative else ""
    alt_text = re.sub(r"[\[\]\n]", " ", alt_text).strip()
    return f"![{alt_text}]({source.group(1) or source.group(2)})"
