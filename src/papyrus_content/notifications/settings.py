"""What the function reads from its environment (set by ``amplify/plugins/notifications/papyrus.plugin.ts``)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Settings:
    site_id: str
    site_origin: str
    base_path: str
    from_name: str
    from_address: str
    configuration_set: str
    item_url_style: str
    theme: Mapping[str, Any]
    lists: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] = os.environ) -> "Settings":
        return cls(
            site_id=environment["SITE_ID"],
            site_origin=environment["SITE_ORIGIN"],
            base_path=environment.get("SITE_BASE_PATH", ""),
            from_name=environment["FROM_NAME"],
            from_address=environment["FROM_ADDRESS"],
            configuration_set=environment.get("CONFIGURATION_SET", ""),
            item_url_style=environment.get("ITEM_URL_STYLE", "html"),
            theme=json.loads(environment["THEME_JSON"]),
            lists=tuple(json.loads(environment.get("LISTS_JSON", "[]"))),
        )
