"""Guard: every ModelAttachment role the Python side writes is accepted by the upload Lambda.

The model-attachment-upload handler rejects roles outside ALLOWED_ROLES, so a role added on the
Python side (e.g. priming_attempts) but not in the allow-list fails in production only.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HANDLER = ROOT / "amplify/functions/model-attachment-upload/handler.ts"
SRC = ROOT / "src"

# Files whose literal "role": "x" / role="x" values are ModelAttachment roles.
LITERAL_FILES = [
    "papyrus_content/model_attachments.py",
    "papyrus_content/newsroom_commands.py",
    "papyrus_content/analysis_commands.py",
]
# Roles written directly to storage by rehydration, never through the upload Lambda.
NOT_UPLOADED = {"record"}
# Constants named *ROLE that are not attachment roles (an agent's job description, a reader's role).
NOT_ATTACHMENT_CONSTANTS = {"PAPYRUS_RUNTIME_ROLE"}

# A role constant is named ROLE or ends in _ROLE (guidelines/store.py names its document role plain ROLE, which the older pattern missed).
_CONST = re.compile(r'^((?:[A-Z][A-Z0-9_]*_)?ROLE)\s*=\s*"([a-z_]+)"', re.MULTILINE)
_ROLE_MAP = re.compile(r'^ROLE_BY_[A-Z_]+\s*=\s*\{(.*?)\}', re.MULTILINE | re.DOTALL)
_LITERAL = re.compile(r'(?:"role":\s*|\brole=)"([a-z_]+)"')


def allowed_roles() -> set[str]:
    text = HANDLER.read_text()
    block = re.search(r"const ALLOWED_ROLES = new Set\(\[(.*?)\]\)", text, re.DOTALL)
    assert block, "ALLOWED_ROLES not found in handler.ts"
    return set(re.findall(r'"([a-z_]+)"', block.group(1)))


def python_roles() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in SRC.rglob("*.py"):
        for name, value in _CONST.findall(path.read_text()):
            if name not in NOT_ATTACHMENT_CONSTANTS:
                found[value] = f"{path.relative_to(ROOT)}:{name}"
        for table in _ROLE_MAP.findall(path.read_text()):
            for value in re.findall(r':\s*"([a-z_]+)"', table):
                found[value] = f"{path.relative_to(ROOT)}:ROLE_BY_*"
    for rel in LITERAL_FILES:
        for value in _LITERAL.findall((SRC / rel).read_text()):
            found.setdefault(value, rel)
    return found


def test_extraction_sees_known_roles():
    roles = python_roles()
    assert {"priming_outcome", "priming_attempts", "metadata", "doctrine_document", "doctrine_asset", "visual_example", "image_record"} <= set(roles)


def test_every_python_attachment_role_is_allowed_by_the_upload_lambda():
    allowed = allowed_roles()
    missing = {r: src for r, src in python_roles().items() if r not in allowed and r not in NOT_UPLOADED}
    assert not missing, f"Roles written by Python but missing from ALLOWED_ROLES in {HANDLER.name}: {missing}"
