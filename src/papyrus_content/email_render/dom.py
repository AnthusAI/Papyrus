"""A tiny DOM for the Markus HTML fragment (stdlib ``html.parser`` only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID_TAGS = frozenset({"img", "br", "hr", "input", "meta", "link", "wbr"})
DROP_TAGS = frozenset({"script", "style", "iframe", "object", "embed", "form", "link", "meta", "noscript"})


@dataclass
class Node:
    tag: str | None  # None for text nodes
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    text: str = ""


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack: list[Node] = [self.root]
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth or tag in DROP_TAGS:
            if tag in DROP_TAGS and tag not in VOID_TAGS:
                self.skip_depth += 1
            return
        node = Node(tag, {k: (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and not self.skip_depth and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            if tag in DROP_TAGS:
                self.skip_depth -= 1
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.stack[-1].children.append(Node(None, text=data))


def parse_fragment(html: str) -> Node:
    builder = _Builder()
    builder.feed(html)
    builder.close()
    return builder.root
