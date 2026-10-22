"""What the signup plugin opens to a guest, pinned from the schema source, and how its static file ships."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from papyrus_content.projection.plugins import PLUGINS_ENV, plugin_names_from_environment, plugin_static_files
from papyrus_content.projection.projector import MarkusSiteProjector

REPOSITORY = Path(__file__).resolve().parents[3]
PLUGIN_SCHEMA = (REPOSITORY / "amplify" / "plugins" / "signup" / "schema.ts").read_text(encoding="utf-8")
BASE_SCHEMAS = [
    (REPOSITORY / "amplify" / "data" / "schema.ts").read_text(encoding="utf-8"),
    (REPOSITORY / "amplify" / "data" / "resource.ts").read_text(encoding="utf-8"),
]
SIGNUP_KEY = "_plugins/papyrus-signup@1.js"


def definition_blocks(source: str) -> dict[str, str]:
    starts = list(re.finditer(r"^    ([A-Za-z]+): a$|^    ([A-Za-z]+): a\.", source, re.MULTILINE))
    return {
        (start.group(1) or start.group(2)): source[start.start() : starts[position + 1].start() if position + 1 < len(starts) else len(source)]
        for position, start in enumerate(starts)
    }


class SignupSchemaSurfaceTests(unittest.TestCase):
    def test_only_the_submit_mutation_is_open_to_guests(self) -> None:
        with_guest = {name for name, block in definition_blocks(PLUGIN_SCHEMA).items() if "allow.guest" in block}
        self.assertEqual(with_guest, {"submitSignup"})
        self.assertEqual(PLUGIN_SCHEMA.count("allow.guest"), 1)

    def test_entries_are_never_guest_or_key_or_custom_readable(self) -> None:
        block = definition_blocks(PLUGIN_SCHEMA)["SignupEntry"]
        for forbidden in ["allow.guest", "publicApiKey", "allow.custom", "allow.public", "allow.authenticated", "allow.owner"]:
            self.assertNotIn(forbidden, block)
        self.assertEqual(sorted(re.findall(r'allow\.group\(([^)]*)\)\.to\(\[([^\]]*)\]\)', block)), [
            ('"admin"', '"read", "delete"'),
            ('"editor"', '"read"'),
        ])
        self.assertEqual(block.count("allow."), 2)

    def test_nobody_can_create_an_entry_through_the_model(self) -> None:
        self.assertNotIn('"create"', definition_blocks(PLUGIN_SCHEMA)["SignupEntry"])
        self.assertNotIn('"update"', definition_blocks(PLUGIN_SCHEMA)["SignupEntry"])

    def test_the_base_schemas_know_nothing_of_the_plugin(self) -> None:
        for source in BASE_SCHEMAS:
            self.assertNotIn("SignupEntry", source)
            self.assertNotIn("submitSignup", source)


class PluginStaticFileTests(unittest.TestCase):
    def test_signup_ships_its_component_under_a_versioned_name(self) -> None:
        files = plugin_static_files(["signup"])
        self.assertEqual(list(files), [SIGNUP_KEY])
        self.assertIn(b"papyrus-signup", files[SIGNUP_KEY])

    def test_an_unknown_plugin_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            plugin_static_files(["newsletters"])

    def test_plugin_names_come_from_the_environment(self) -> None:
        self.assertEqual(plugin_names_from_environment({PLUGINS_ENV: "signup, other,"}), ("signup", "other"))
        self.assertEqual(plugin_names_from_environment({}), ())

    def test_a_site_without_plugins_gets_exactly_the_files_it_got_before(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plain = MarkusSiteProjector.from_static_directory(Path(temporary))
            enabled = MarkusSiteProjector.from_static_directory(Path(temporary), plugins=("signup",))
            self.assertNotIn(SIGNUP_KEY, plain.static_files())
            self.assertEqual({key for key in enabled.static_files()} - {key for key in plain.static_files()}, {SIGNUP_KEY})
            self.assertEqual(plain.version, enabled.version)

    def test_the_projection_runtime_enables_plugins_from_the_environment(self) -> None:
        from papyrus_content.projection.runtime import load_projector

        with tempfile.TemporaryDirectory() as temporary:
            with_plugin = load_projector({"PAPYRUS_SITE_STATIC_DIR": temporary, PLUGINS_ENV: "signup"})
            without_plugin = load_projector({"PAPYRUS_SITE_STATIC_DIR": temporary})
            self.assertIn(SIGNUP_KEY, with_plugin.static_files())
            self.assertNotIn(SIGNUP_KEY, without_plugin.static_files())


if __name__ == "__main__":
    unittest.main()
