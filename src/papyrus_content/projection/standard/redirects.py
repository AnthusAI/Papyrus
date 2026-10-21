"""Pattern redirect rules: data that Papyrus compiles into the edge function.

The CloudFront Function cannot read S3 and the KeyValueStore matches whole keys,
so a rule such as ``/blog/<slug>/`` to ``/articles/<slug>/`` cannot live in the
store. A site declares such rules in ``projection.json`` (``redirects.patterns``)
and ``amplify/publication/redirect-rules.ts`` compiles them into the function at
deploy time. This module is the Python definition: it validates a rule, applies
it (for tests and for parity simulation) and serialises it for the compiler.

Patterns use the subset of regular expressions that Python and JavaScript read
the same way (no named groups, lookbehind or inline flags). A target substitutes
``$1`` .. ``$9`` for the pattern's groups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_UNPORTABLE = re.compile(r"\(\?[<P!=]|\(\?[a-zA-Z]+\)|\\[AZzG]")
_SUBSTITUTION = re.compile(r"\$([0-9])")


@dataclass(frozen=True)
class RedirectRule:
    pattern: str
    to: str
    status: int = 301
    except_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _UNPORTABLE.search(self.pattern):
            raise ValueError(f"Redirect pattern uses syntax that differs between Python and JavaScript: {self.pattern!r}")
        try:
            compiled = re.compile(self.pattern)
        except re.error as error:
            raise ValueError(f"Invalid redirect pattern {self.pattern!r}: {error}") from error
        if not self.pattern.startswith("^") or not self.pattern.endswith("$"):
            raise ValueError(f"Redirect pattern must be anchored with ^ and $: {self.pattern!r}")
        if not self.to.startswith(("/", "https://", "http://")):
            raise ValueError(f"Redirect target must be an absolute path or URL: {self.to!r}")
        if self.status not in (301, 302, 307, 308):
            raise ValueError(f"Unsupported redirect status {self.status}")
        for number in _SUBSTITUTION.findall(self.to):
            if int(number) > compiled.groups:
                raise ValueError(f"Redirect target {self.to!r} uses group {number} but the pattern has {compiled.groups}")

    def apply(self, path: str) -> str | None:
        """The redirect target for ``path``, or ``None`` when the rule does not match."""
        if path in self.except_paths:
            return None
        match = re.match(self.pattern, path)
        if match is None:
            return None
        return _SUBSTITUTION.sub(lambda found: match.group(int(found.group(1))) or "", self.to)

    def to_edge_record(self) -> dict:
        return {"p": self.pattern, "t": self.to, "s": self.status, "x": list(self.except_paths)}


def rule_from_mapping(raw: dict) -> RedirectRule:
    unknown = set(raw) - {"pattern", "to", "status", "except"}
    if unknown:
        raise ValueError(f"Unknown redirect rule settings: {', '.join(sorted(unknown))}")
    return RedirectRule(
        pattern=str(raw["pattern"]),
        to=str(raw["to"]),
        status=int(raw.get("status", 301)),
        except_paths=tuple(raw.get("except") or ()),
    )


def first_match(rules, path: str) -> tuple[str, int] | None:
    for rule in rules:
        target = rule.apply(path)
        if target is not None:
            return target, rule.status
    return None
