"""A fake counter table and entry store for the signup handler, with the same contracts as the real ones."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HANDLER_PATH = Path(__file__).resolve().parents[3] / "amplify" / "plugins" / "signup" / "function" / "handler.py"
_specification = importlib.util.spec_from_file_location("signup_handler", HANDLER_PATH)
signup_handler = importlib.util.module_from_spec(_specification)
sys.modules["signup_handler"] = signup_handler
_specification.loader.exec_module(signup_handler)

PLACEHOLDER_ADDRESS = "address@example.test"
START_SECONDS = 1_800_000_000.0
RENDERED_LONG_AGO_MILLISECONDS = str(int((START_SECONDS - 60) * 1000))


class FakeSignupBackend:
    def __init__(self, *, forms=("newsletter",), address_limit=20, identity_limit=5) -> None:
        self.settings = signup_handler.SignupSettings(frozenset(forms), address_limit, identity_limit)
        self.counters: dict[str, int] = {}
        self.entries: dict[str, dict[str, str]] = {}
        self.now = START_SECONDS

    def count_hit(self, key: str, lifetime_seconds: int) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def store_entry(self, entry: dict[str, str]) -> bool:
        if entry["id"] in self.entries:
            return False
        self.entries[entry["id"]] = entry
        return True

    def submit(self, arguments: dict, *, address: str = "198.51.100.7", identity_id: str | None = "identity-1") -> dict:
        return signup_handler.submit_signup(
            arguments,
            address=address,
            identity_id=identity_id,
            now_seconds=self.now,
            settings=self.settings,
            count_hit=self.count_hit,
            store_entry=self.store_entry,
        )


def valid_arguments(**changes) -> dict:
    arguments = {
        "form": "newsletter",
        "value": "reader@example.test",
        "renderedAt": RENDERED_LONG_AGO_MILLISECONDS,
        "website": "",
    }
    arguments.update(changes)
    return arguments
