"""The page-refresh operations as MCP tools, in the shape of the MCP server's ``TOOLS`` and ``DESCRIPTIONS`` tables (``images/mcp.py``).

``TOOLS.update(page_refresh_tools())`` and ``DESCRIPTIONS.update(page_refresh_descriptions())`` add them; ``call_page_refresh_tool`` runs one and
returns the same JSON the command prints. Nothing here depends on the server (PR #1244).
"""

from __future__ import annotations

from typing import Any

from .operations import OPERATIONS, run_operation
from .service import RefreshService


def page_refresh_tools() -> dict[str, tuple[str, dict]]:
    return {operation.name: (operation.audience, operation.input) for operation in OPERATIONS}


def page_refresh_descriptions() -> dict[str, str]:
    return {operation.name: operation.summary for operation in OPERATIONS}


def call_page_refresh_tool(name: str, arguments: Any, service: RefreshService) -> dict:
    return run_operation(name, arguments, service)
