"""The responsibility catalog (pure Python, so the site Lambdas can read it): the work an always-on agent can be given (docs/design/always-on-agents-architecture.md section 2.1).

A responsibility is a key in the agent policy document (``papyrus_content.agent_policy``) and in every definition file. The catalog names them once; a definition
that names another is refused. The keys that the policy document already uses (rate, ideate, improve, translate, announce) are kept as they are.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Responsibility:
    key: str
    title: str
    containers: bool = False   # may run as a container (the knowledge run only; every other responsibility runs as a lambda)


CATALOG: tuple[Responsibility, ...] = (
    Responsibility("intake", "Intake and capture"),
    Responsibility("rate", "Rate and curate"),
    Responsibility("ideate", "Ideate"),
    Responsibility("select", "Select and assign"),
    Responsibility("research", "Research"),
    Responsibility("improve", "Write and copy-edit (improve)"),
    Responsibility("fact_check", "Fact-check"),
    Responsibility("illustrate", "Illustrate"),
    Responsibility("translate", "Translate"),
    Responsibility("announce", "Announce"),
    Responsibility("newsletter", "Newsletter and summaries"),
    Responsibility("learn", "Learn from edits"),
    Responsibility("accept", "Relevance and acceptance"),
    Responsibility("knowledge", "Concepts and knowledge", containers=True),
    Responsibility("hygiene", "Operations hygiene"),
    Responsibility("monitor", "Monitoring collection"),
)

BY_KEY = {item.key: item for item in CATALOG}
