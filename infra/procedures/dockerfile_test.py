"""The procedure runner image installs Caducus at the same exact pin as the notifications function: the announce agent builds the site's
notifications runtime (its X and email channels) inside the runner, and that runtime imports Caducus."""
from __future__ import annotations

import re
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]


def test_the_runner_image_installs_the_caducus_pin_the_notifications_function_uses():
    plugin = (REPOSITORY / "amplify" / "plugins" / "notifications" / "papyrus.plugin.ts").read_text(encoding="utf-8")
    pin = re.search(r'CADUCUS_REQUIREMENT = "([^"]+)"', plugin).group(1)
    dockerfile = (REPOSITORY / "infra" / "procedures" / "Dockerfile").read_text(encoding="utf-8")
    assert f'"{pin}"' in dockerfile
