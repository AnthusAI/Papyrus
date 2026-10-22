"""Bundle entry for the newsroom's newsletter operations (AppSync): forwards to the ``newsletter`` function.

The logic is ``papyrus_content.newsletter.ops_proxy`` (src/papyrus_content/newsletter/ops_proxy.py).
"""

from typing import Any

from papyrus_content.newsletter.ops_proxy import handle


def handler(event: dict[str, Any], _context: Any = None) -> Any:
    return handle(event)
