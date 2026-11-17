"""Walk a pod and read each note's front matter.

A note is a Markdown file (``.md``) anywhere under the pod, in any folder; folders mean nothing to the graph. Folders and files whose name starts with a
dot (``.git``) are not part of the pod, and neither are files that are not Markdown. Front matter is a YAML mapping between two ``---`` lines at
the very top of the file. A note with no front matter is a plain note, which is never wrong.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FENCE = "---"


@dataclass
class Note:
    path: str                       # relative to the pod, with forward slashes
    front: dict | None = None       # the front matter mapping, None when the note has none
    body: str = ""
    problem: str | None = None      # why the front matter could not be read
    keys: list[str] = field(default_factory=list)

    @property
    def stem(self) -> str:
        return self.path.rsplit("/", 1)[-1].removesuffix(".md")

    @property
    def typed(self) -> bool:
        """A note is typed when it carries a ``type`` or an ``id``; every other note is a plain note and its front matter is its own."""
        return self.front is not None and ("type" in self.front or "id" in self.front)


class _Loader(yaml.SafeLoader):
    """YAML that refuses a repeated key, which plain YAML silently resolves to the last one."""


def _mapping(loader: _Loader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise yaml.constructor.ConstructorError(None, None, f"the key {key!r} appears twice", key_node.start_mark)
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse(text: str) -> tuple[dict | None, str, str | None]:
    """Split a note into (front matter, body, problem). A problem means the front matter is there but unusable."""
    lines = text.lstrip("﻿").splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != FENCE:
        return None, text, None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == FENCE:
            raw = "".join(lines[1:index])
            body = "".join(lines[index + 1:])
            try:
                loaded = yaml.load(raw, Loader=_Loader)
            except yaml.YAMLError as error:
                detail = str(error).replace("\n", " ")
                return None, body, f"front matter is not valid YAML: {detail}"
            if loaded is None:
                return {}, body, None
            if not isinstance(loaded, dict):
                return None, body, "front matter must be a mapping of keys to values"
            if any(not isinstance(key, str) for key in loaded):
                return None, body, "every front matter key must be text"
            return loaded, body, None
    return None, text, "front matter opens with --- and is never closed with a second ---"


def body_hash(body: str) -> str:
    """The hash a ``reviewedHash`` holds: ``sha256:`` and the hex digest of the body's UTF-8 text, with Windows line ends read as plain newlines."""
    return "sha256:" + hashlib.sha256(body.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def walk(pod: Path) -> list[Note]:
    """Every note of the pod, in path order."""
    notes: list[Note] = []
    for file in sorted(pod.rglob("*.md")):
        relative = file.relative_to(pod)
        if not file.is_file() or any(part.startswith(".") for part in relative.parts):
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            notes.append(Note(relative.as_posix(), None, "", "is not UTF-8 text"))
            continue
        front, body, problem = parse(text)
        notes.append(Note(relative.as_posix(), front, body, problem, list(front) if front else []))
    return notes
