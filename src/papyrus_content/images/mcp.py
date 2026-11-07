"""The image operations as MCP tools: the generated schema, and a call that runs the same ``execute`` as the CLI.

``image_tools()`` and ``image_descriptions()`` have the shape of the MCP server's ``TOOLS`` and ``DESCRIPTIONS`` tables (``name -> (audience, input
schema)`` and ``name -> sentence``), so the MCP server (PR #1244, wired in a later build step) adds them with ``TOOLS.update(image_tools())``.
Nothing here depends on that server.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .handlers import Caller, Handler, execute

SCHEMA_FILE = Path(__file__).with_name("mcp_tools.generated.json")


@lru_cache(maxsize=1)
def _tools() -> list[dict]:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))["tools"]


def image_tools() -> dict[str, tuple[str, dict]]:
    return {tool["name"]: (tool["audience"], tool["inputSchema"]) for tool in _tools()}


def image_descriptions() -> dict[str, str]:
    return {tool["name"]: tool["description"] for tool in _tools()}


def image_output_schemas() -> dict[str, dict]:
    return {tool["name"]: tool["outputSchema"] for tool in _tools()}


def caller_from_principal(principal: Any) -> Caller:
    """A staff principal as a caller: an agent when the principal says so (``is_agent``), a person otherwise."""
    return Caller(kind="agent" if getattr(principal, "is_agent", False) else "person", subject=getattr(principal, "subject", "") or "",
                  delegated_by=getattr(principal, "delegated_by", None))


def call_image_tool(name: str, arguments: dict, caller: Caller, handlers: dict[str, Handler] | None = None) -> dict:
    """Run one tool and return its envelope: the same JSON the command prints."""
    return execute(name, arguments, caller, handlers)
