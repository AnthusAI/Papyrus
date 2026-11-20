"""Reading and writing the flat front matter of a guideline file with the standard library alone.

Guidelines are read where PyYAML is not bundled (the site's data-API functions are built with no third-party packages), so the front matter of the guideline file form is
a small, strict subset of YAML that this module reads and writes itself: one ``key: value`` line per key; a value is text (plain, ``"double quoted"`` or ``'single quoted'``),
a number, ``true``, ``false`` or ``null``, or a flat list of those, written inline (``["a", "b"]``) or as ``- item`` lines under the key. Nothing nested, no anchors, no block
text. A value that is nested, or a line that is not ``key: value``, is read as a nested value or refused, so the file form's own checks name the problem. A file written by
PyYAML for flat keys is in this subset.
"""
from __future__ import annotations

import json
import re
from typing import Any

_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:[ \t]+(.*))?$")
_NUMBER = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?\d+\.\d+$")
_SPECIAL_START = set("&*!|>%@`")


class FrontMatterError(ValueError):
    pass


def _strip_comment(text: str) -> str:
    found = re.search(r"\s#", text)
    return text[: found.start()] if found else text


def _quoted(text: str) -> tuple[str, str]:
    """``(value, rest)`` of a quoted text at the start of ``text``."""
    if text[0] == '"':
        try:
            value, end = json.JSONDecoder().raw_decode(text)
        except ValueError as error:
            raise FrontMatterError("has a double-quoted text that is not valid") from error
        if not isinstance(value, str):
            raise FrontMatterError("has a double-quoted text that is not valid")
        return value, text[end:]
    out, index = [], 1
    while index < len(text):
        if text[index] == "'":
            if text[index + 1: index + 2] == "'":
                out.append("'")
                index += 2
                continue
            return "".join(out), text[index + 1:]
        out.append(text[index])
        index += 1
    raise FrontMatterError("has a single-quoted text that is not closed")


def _plain(text: str) -> Any:
    text = _strip_comment(text).strip()
    if text and text[0] in _SPECIAL_START:
        raise FrontMatterError(f"has a value that starts with {text[0]!r}, which is not part of the flat front matter")
    if text in ("", "~", "null", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if _NUMBER.match(text):
        return int(text)
    if _FLOAT.match(text):
        return float(text)
    return text


def _flow_items(text: str) -> list[Any]:
    """The items of the inside of ``[ ... ]``."""
    items: list[Any] = []
    rest = text.strip()
    while rest:
        if rest[0] in "\"'":
            value, rest = _quoted(rest)
            items.append(value)
        elif rest[0] == "[":
            depth, end = 0, None
            for position, char in enumerate(rest):
                depth += char == "["
                depth -= char == "]"
                if depth == 0:
                    end = position
                    break
            if end is None:
                raise FrontMatterError("has a list that is not closed")
            items.append(_flow_items(rest[1:end]))
            rest = rest[end + 1:]
        elif rest[0] == "{":
            items.append({"nested": True})
            rest = rest[rest.index("}") + 1:] if "}" in rest else ""
        else:
            end = rest.find(",")
            items.append(_plain(rest if end < 0 else rest[:end]))
            rest = "" if end < 0 else rest[end:]
        rest = rest.lstrip()
        if rest.startswith(","):
            rest = rest[1:].lstrip()
        elif rest:
            raise FrontMatterError("has a list whose items are not separated by commas")
    return items


def _value(text: str) -> Any:
    text = text.strip()
    if text.startswith(("{",)):
        return {"nested": True}
    if text.startswith("["):
        body = _strip_comment(text).strip()
        if not body.endswith("]"):
            raise FrontMatterError("has a list that is not closed")
        return _flow_items(body[1:-1])
    if text[:1] in "\"'":
        value, rest = _quoted(text)
        if _strip_comment(rest).strip():
            raise FrontMatterError("has text after a quoted value")
        return value
    return _plain(text)


def _item(text: str) -> Any:
    text = text.strip()
    if text.startswith("- ") or text == "-":
        return [_item(text[1:])] if text[1:].strip() else [None]
    if text[:1] not in "\"'[{" and re.match(r"^[^\s:][^:]*:(?:\s|$)", text):
        return {"nested": True}
    return _value(text) if text else None


def _block(lines: list[str]) -> Any:
    """The value of a key with nothing after the colon: the lines under it."""
    content = [line for line in lines if line.strip() and not line.strip().startswith("#")]
    if content and all(line.lstrip().startswith("-") and (line.lstrip() == "-" or line.lstrip()[1] in " \t") for line in content):
        return [_item(line.lstrip()[1:]) for line in content]
    return {"nested": True}


def loads(text: str) -> dict[str, Any]:
    lines = text.replace("\r\n", "\n").split("\n")
    result: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        found = _KEY.match(line)
        if found is None:
            raise FrontMatterError(f"has a line that is not 'key: value': {line.strip()[:60]!r}")
        key, rest = found.group(1), (found.group(2) or "").strip()
        if key in result:
            raise FrontMatterError(f"has the key {key} twice")
        if rest == "" or rest.startswith("#"):
            block: list[str] = []
            while index < len(lines) and (not lines[index].strip() or lines[index][0] in " \t-#"):
                block.append(lines[index])
                index += 1
            result[key] = _block(block) if any(item.strip() for item in block) else None
        else:
            result[key] = _value(rest)
    return result


def dump_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(str(value), ensure_ascii=False)


def dumps(meta: dict[str, Any]) -> str:
    """The front matter lines of a flat mapping: texts always double-quoted, lists inline."""
    lines = []
    for key, value in meta.items():
        shown = "[" + ", ".join(dump_scalar(item) for item in value) + "]" if isinstance(value, list) else dump_scalar(value)
        lines.append(f"{key}: {shown}")
    return "\n".join(lines) + "\n"
