#!/usr/bin/env python3
"""Build the deterministic collector or router zip; optionally upload it by content hash.

  python3 infra/monitoring/build.py                         # collector zip: print SHA256 and S3 key
  python3 infra/monitoring/build.py --router                # router zip (package closure, YAML data, pure-Python PyYAML)
  python3 infra/monitoring/build.py --router --upload BUCKET  # also upload (needs AWS_PROFILE; asserts the account)

Each zip holds only the modules its Lambda imports. The collector zip is unchanged by the
router, so deploying the router never touches the collector function. Prints no secrets.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MODULES = ("__init__.py", "monitoring.py", "monitoring_cloud.py")
ACCOUNT = "712236451410"
OUT = Path(__file__).resolve().parent / "dist" / "papyrus-monitoring.zip"
ROUTER_OUT = Path(__file__).resolve().parent / "dist" / "papyrus-monitoring-router.zip"
PACKAGE = ROOT / "src" / "papyrus_content"
ROUTER_ROOTS = ("monitoring_router", "monitoring_intake", "editorial_context", "graphql_authoring", "graphql_http")
# Imported lazily on paths the router never runs; they need packages the Lambda does not have.
ROUTER_EXCLUDED = frozenset({"web_structured_metadata", "biblicus_runner"})
ROUTER_DATA = ("corpora/papyrus-semantic-relation-types.yml", "corpora/papyrus-publication-doctrine.yml")


def build(out: Path = OUT) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(MODULES):
            info = zipfile.ZipInfo(f"papyrus_content/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (ROOT / "src" / "papyrus_content" / name).read_bytes())
    return hashlib.sha256(out.read_bytes()).hexdigest()


def router_modules() -> list[str]:
    """Transitive closure of in-package imports (module level and lazy) from the router roots."""
    seen, stack = set(), list(ROUTER_ROOTS)
    while stack:
        name = stack.pop()
        if name in seen or name in ROUTER_EXCLUDED:
            continue
        seen.add(name)
        for node in ast.walk(ast.parse((PACKAGE / f"{name}.py").read_text())):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                stack.extend([node.module] if node.module else [alias.name for alias in node.names])
    return sorted(seen)


def _add(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.external_attr = 0o644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


def build_router(out: Path = ROUTER_OUT) -> str:
    """Router zip: package modules, the two YAML data files they read, and pure-Python PyYAML.

    The Lambda runtime has boto3/botocore only. PyYAML is copied without its C extension, so it
    runs in its pure-Python mode on arm64. PAPYRUS_ROOT=/var/task makes `corpora/` resolve.
    """
    import yaml

    out.parent.mkdir(parents=True, exist_ok=True)
    entries = {f"papyrus_content/{name}.py": (PACKAGE / f"{name}.py").read_bytes() for name in router_modules()}
    entries["papyrus_content/__init__.py"] = (PACKAGE / "__init__.py").read_bytes()
    for relative in ROUTER_DATA:
        entries[relative] = (ROOT / relative).read_bytes()
    for path in Path(yaml.__file__).parent.glob("*.py"):
        entries[f"yaml/{path.name}"] = path.read_bytes()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            _add(archive, name, entries[name])
    return hashlib.sha256(out.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", metavar="BUCKET")
    parser.add_argument("--router", action="store_true", help="build the router zip instead of the collector zip")
    args = parser.parse_args()
    digest, out = (build_router(), ROUTER_OUT) if args.router else (build(), OUT)
    key = f"papyrus-monitoring/{'router-' if args.router else ''}{digest}.zip"
    print(f"SHA256 {digest}\nCodeKey {key}\nSize {out.stat().st_size} bytes")
    if args.upload:
        account = subprocess.run(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
                                 check=True, capture_output=True, text=True).stdout.strip()
        if account != ACCOUNT:
            print(f"Refusing to upload: caller account is not {ACCOUNT}", file=sys.stderr)
            return 2
        subprocess.run(["aws", "s3", "cp", str(out), f"s3://{args.upload}/{key}", "--only-show-errors"], check=True)
        print(f"Uploaded s3://{args.upload}/{key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
