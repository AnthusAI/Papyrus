"""The topic operations as MCP tools: the generated schema, and a call that runs the same ``execute`` as the CLI.

``topic_tools()`` and ``topic_descriptions()`` have the shape of the MCP server's ``TOOLS`` and ``DESCRIPTIONS`` tables (``name -> (audience, input
schema)`` and ``name -> sentence``), the same as ``images/mcp.py``, so the MCP server adds them the same way. Nothing here depends on that server.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from papyrus_content.images.handlers import Caller, Handler

from .handlers import execute

SCHEMA_FILE = Path(__file__).with_name("mcp_tools.generated.json")


@lru_cache(maxsize=1)
def _tools() -> list[dict]:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))["tools"]


def topic_tools() -> dict[str, tuple[str, dict]]:
    return {tool["name"]: (tool["audience"], tool["inputSchema"]) for tool in _tools()}


def topic_descriptions() -> dict[str, str]:
    return {tool["name"]: tool["description"] for tool in _tools()}


def call_topic_tool(name: str, arguments: dict, caller: Caller, handlers: dict[str, Handler] | None = None) -> dict:
    """Run one tool and return its envelope: the same JSON the command prints."""
    if handlers is None:
        from .handlers import signed_in_handlers

        handlers = signed_in_handlers()
    return execute(name, arguments, caller, handlers)
