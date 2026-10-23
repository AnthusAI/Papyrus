from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGED_DIRECTORY = "papyrus_content/data/corpora"
SOURCE_DIRECTORY = REPO_ROOT / "src" / "papyrus_content" / "data" / "corpora"

# `corpora/<name>` defaults that runtime code names literally (a quoted path or a `"corpora" / "<name>"` join).
_DEFAULT_PATTERN = re.compile(r"""["']corpora/(papyrus-[\w.-]+\.(?:ya?ml|json))["']""")


def runtime_default_corpora_names() -> set[str]:
    names: set[str] = set()
    for root in ("papyrus_content", "papyrus_newsroom", "papyrus_knowledge_query", "papyrus"):
        for path in (REPO_ROOT / "src" / root).rglob("*.py"):
            if path.name.endswith("_test.py"):
                continue
            names.update(_DEFAULT_PATTERN.findall(path.read_text(encoding="utf-8")))
    return names


def build_wheel(destination: Path) -> Path:
    poetry = shutil.which("poetry")
    if poetry is None:
        raise RuntimeError("poetry is required to build the wheel")
    subprocess.run([poetry, "build", "--format", "wheel", "--output", str(destination)], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    return next(destination.glob("papyrus_newsroom-*.whl"))


def wheel_members(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())


def install_wheel(wheel: Path, target: Path) -> None:
    """Unpack the wheel the way pip lays it out in site-packages."""
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(target)


def run_installed(target: Path, workdir: Path, code: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    script = f"import sys; sys.path.insert(0, {str(target)!r})\n{code}"
    return subprocess.run([sys.executable, "-c", script], cwd=workdir, env=env, capture_output=True, text=True)
