#!/usr/bin/env python3
"""Build the deterministic collector or router zip; optionally upload it by content hash.

  python3 infra/monitoring/build.py                         # collector zip: print SHA256 and S3 key
  python3 infra/monitoring/build.py --router                # router zip (package closure, YAML data, pure-Python PyYAML)
  python3 infra/monitoring/build.py --router --host         # router zip with this machine's own wheels (tests; not for the Lambda)
  python3 infra/monitoring/build.py --email                 # strict SES submission receiver
  python3 infra/monitoring/build.py --router --upload BUCKET  # also upload (needs AWS_PROFILE; asserts the account)

Each zip holds only the modules its Lambda imports. The collector zip is unchanged by the
router, so deploying the router never touches the collector function. Prints no secrets.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.metadata
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[2]
# The collector zip holds the import closure of these roots (computed, so a new module is never left out).
COLLECTOR_ROOTS = ("monitoring_cloud", "monitoring", "monitoring_huggingface")
ACCOUNT = "712236451410"
OUT = Path(__file__).resolve().parent / "dist" / "papyrus-monitoring.zip"
ROUTER_OUT = Path(__file__).resolve().parent / "dist" / "papyrus-monitoring-router.zip"
EMAIL_OUT = Path(__file__).resolve().parent / "dist" / "papyrus-email-submissions.zip"
PACKAGE = ROOT / "src" / "papyrus_content"
ROUTER_ROOTS = ("monitoring_router", "monitoring_intake", "editorial_context", "graphql_authoring", "graphql_http",
                # papyrus_knowledge_query (below) imports these from papyrus_content, which the closure cannot see from outside the package
                "knowledge_snapshot/keys", "knowledge_wiki/pages", "corpus_storage_paths")
# The vector pass of the monitor-stories task (monitoring_vectors.py) runs the knowledge-query package's vector index and S3 Vectors provider.
# It is standard-library only; its command line and Lambda handler are not needed.
KNOWLEDGE_QUERY_PACKAGE = ROOT / "src" / "papyrus_knowledge_query"
KNOWLEDGE_QUERY_EXCLUDED = frozenset({"cli.py", "lambda_handler.py"})
# Imported only inside functions on paths the router never runs; they need packages the Lambda does not have.
ROUTER_EXCLUDED = frozenset({"biblicus_runner"})
# Pure-Python packages copied into the worker zips (the Lambda runtime has boto3/botocore only): PyYAML, then youtube-transcript-api and
# everything it imports. Compiled extensions are left out; each package runs in its pure-Python mode.
VENDORED = ("yaml", "youtube_transcript_api", "defusedxml", "requests", "urllib3", "idna", "certifi", "charset_normalizer")
VENDORED_DATA = frozenset({".py", ".pem"})
# The editorial gate (ideas/gate.py -> editorial_checks) imports Humanus, and its judgment lane imports typesafe_sdk (the `jev` extra). Their
# dependency closure comes from poetry.lock at the locked versions, as binary wheels for the Lambda (arm64, CPython 3.13), unpacked into the zip.
# Packages VENDORED already covers (idna, PyYAML) are left to that path, and the Lambda runtime brings boto3 and botocore.
LOCK = ROOT / "poetry.lock"
# anthus-markus renders the Markus body of every filed idea (publishing.derive_body); it turns on markdown-it-py's linkify extra, which the
# closure leaves out with the other extras, so linkify-it-py is named too.
ROUTER_WHEEL_ROOTS = ("humanus", "typesafe-sdk", "anthus-markus", "linkify-it-py")
LAMBDA_PLATFORMS = ("manylinux_2_28_aarch64", "manylinux_2_17_aarch64", "manylinux2014_aarch64")
LAMBDA_PYTHON = "3.13"
ROUTER_DATA = ("corpora/papyrus-semantic-relation-types.yml", "corpora/papyrus-publication-doctrine.yml")


def build(out: Path = OUT) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["__init__.py", *(f"{module}.py" for module in package_modules(COLLECTOR_ROOTS))]:
            info = zipfile.ZipInfo(f"papyrus_content/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (ROOT / "src" / "papyrus_content" / name).read_bytes())
    return hashlib.sha256(out.read_bytes()).hexdigest()


def _module_names(node: ast.ImportFrom, module: str = "") -> list[str]:
    """In-package modules (as paths like `ideas/synthesis`) one `from ... import` in `module` may load: relative (`from .x import y`,
    `from ..x import y`, resolved against the importing module's own package) and absolute (`from papyrus_content.x import y`,
    `from papyrus_content import x`) forms, subpackages and their `__init__`. `module` is the importing module's path (`ideas/monitor_stories`)."""
    if node.level >= 1:
        package = module.split("/")[:-1]
        keep = len(package) - (node.level - 1)
        if keep < 0:
            return []
        base = "/".join(package[:keep] + [part for part in (node.module or "").split(".") if part])
    elif node.level == 0 and node.module == "papyrus_content":
        base = ""
    elif node.level == 0 and (node.module or "").startswith("papyrus_content."):
        base = node.module[len("papyrus_content."):].replace(".", "/")
    else:
        return []
    names = []
    if base and (PACKAGE / f"{base}.py").exists():
        names.append(base)
    if base and (PACKAGE / base / "__init__.py").exists():
        names.append(f"{base}/__init__")
    for alias in node.names:
        child = f"{base}/{alias.name}" if base else alias.name
        if (PACKAGE / f"{child}.py").exists():
            names.append(child)
    return names


def package_modules(roots) -> list[str]:
    """Transitive closure of in-package imports (module level and lazy). A module in a subpackage brings the `__init__` of every package
    above it, as Python imports them first."""
    seen, stack = set(), list(roots)
    while stack:
        name = stack.pop()
        if name in seen or name in ROUTER_EXCLUDED:
            continue
        seen.add(name)
        parts = name.split("/")
        stack.extend("/".join(parts[:depth] + ["__init__"]) for depth in range(1, len(parts)) if (PACKAGE / "/".join(parts[:depth]) / "__init__.py").exists())
        for node in ast.walk(ast.parse((PACKAGE / f"{name}.py").read_text())):
            if isinstance(node, ast.ImportFrom):
                stack.extend(_module_names(node, name))
    return sorted(seen)


def router_modules() -> list[str]:
    return package_modules(ROUTER_ROOTS)


def _add(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.external_attr = 0o644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_wheel_packages(roots=ROUTER_WHEEL_ROOTS) -> dict[str, dict]:
    """The poetry.lock entries (name -> package) of `roots` and everything they depend on, optional extras left out, minus the VENDORED ones."""
    packages = {_canonical(entry["name"]): entry for entry in tomllib.loads(LOCK.read_text())["package"]}
    vendored = {_canonical(name) for name in ("pyyaml", "idna", *VENDORED)}
    seen, stack = {}, list(roots)
    while stack:
        name = _canonical(stack.pop())
        if name in seen:
            continue
        seen[name] = packages[name]
        stack.extend(dep for dep, spec in packages[name].get("dependencies", {}).items()
                     if not (isinstance(spec, dict) and spec.get("optional")) and _canonical(dep) not in vendored)
    return {name: seen[name] for name in sorted(seen)}


def _lambda_wheel_entries(packages: dict[str, dict]) -> dict[str, bytes]:
    """Download each locked package's binary wheel for the Lambda platform, check its sha256 against poetry.lock, and return its files."""
    entries: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory() as scratch:
        for name, entry in packages.items():
            target = Path(scratch) / name
            subprocess.run([sys.executable, "-m", "pip", "download", "--quiet", "--disable-pip-version-check", "--no-deps", "--only-binary=:all:", "--implementation", "cp",
                            "--python-version", LAMBDA_PYTHON, "--abi", f"cp{LAMBDA_PYTHON.replace('.', '')}",
                            *(arg for platform in (*LAMBDA_PLATFORMS, "any") for arg in ("--platform", platform)),
                            "--dest", str(target), f"{name}=={entry['version']}"], check=True)
            wheels = list(target.glob("*.whl"))
            assert len(wheels) == 1, (name, wheels)
            locked = {item["hash"].removeprefix("sha256:") for item in entry["files"]}
            digest = hashlib.sha256(wheels[0].read_bytes()).hexdigest()
            assert digest in locked, f"{wheels[0].name} is not in poetry.lock for {name} (sha256 {digest})"
            with zipfile.ZipFile(wheels[0]) as wheel:
                for member in wheel.namelist():
                    if not member.endswith("/") and "__pycache__" not in member:
                        entries[member] = wheel.read(member)
    return entries


def _host_wheel_entries(packages: dict[str, dict]) -> dict[str, bytes]:
    """The same packages as installed in this interpreter (for tests that import the zip on the host platform)."""
    entries: dict[str, bytes] = {}
    for name in packages:
        distribution = importlib.metadata.distribution(name)
        for file in distribution.files or ():
            if "__pycache__" not in file.parts and not file.name.endswith(".pyc") and file.parts[0] != "..":
                entries[file.as_posix()] = Path(distribution.locate_file(file)).read_bytes()
    return entries


def knowledge_query_files() -> dict[str, bytes]:
    return {f"papyrus_knowledge_query/{path.name}": path.read_bytes() for path in sorted(KNOWLEDGE_QUERY_PACKAGE.glob("*.py")) if path.name not in KNOWLEDGE_QUERY_EXCLUDED}


def build_package(out: Path, roots, wheels: str | None = None, with_knowledge_query: bool = False) -> str:
    """Worker zip: package modules, the two YAML data files they read, and the pure-Python VENDORED packages.

    The Lambda runtime has boto3/botocore only. PyYAML is copied without its C extension, so it
    runs in its pure-Python mode on arm64. PAPYRUS_ROOT=/var/task makes `corpora/` resolve.
    """

    out.parent.mkdir(parents=True, exist_ok=True)
    entries = {}
    if wheels:
        packages = locked_wheel_packages()
        entries.update(_host_wheel_entries(packages) if wheels == "host" else _lambda_wheel_entries(packages))
    entries |= {f"papyrus_content/{name}.py": (PACKAGE / f"{name}.py").read_bytes() for name in package_modules(roots)}
    entries["papyrus_content/__init__.py"] = (PACKAGE / "__init__.py").read_bytes()
    if with_knowledge_query:
        entries |= knowledge_query_files()
    for relative in ROUTER_DATA:
        entries[relative] = (ROOT / relative).read_bytes()
    for name in VENDORED:
        root = Path(importlib.import_module(name).__file__).parent
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if path.suffix in VENDORED_DATA and "test" not in relative.parts and "__pycache__" not in relative.parts:
                entries[f"{name}/{relative.as_posix()}"] = path.read_bytes()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            _add(archive, name, entries[name])
    return hashlib.sha256(out.read_bytes()).hexdigest()


def build_router(out: Path = ROUTER_OUT, target: str = "lambda") -> str:
    """`target` is "lambda" (wheels for the function, fetched and checked against poetry.lock) or "host" (this interpreter's installed copies)."""
    return build_package(out, ROUTER_ROOTS, wheels=target, with_knowledge_query=True)


def build_email(out: Path = EMAIL_OUT) -> str:
    return build_package(out, ("email_submission_intake",))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", metavar="BUCKET")
    worker = parser.add_mutually_exclusive_group()
    worker.add_argument("--router", action="store_true", help="build the router zip instead of the collector zip")
    worker.add_argument("--email", action="store_true", help="build the strict email submission receiver zip")
    parser.add_argument("--host", action="store_true", help="with --router: use this machine's installed packages instead of Lambda wheels (tests only)")
    args = parser.parse_args()
    if args.host and not args.router:
        parser.error("--host goes with --router")
    digest, out = ((build_email(), EMAIL_OUT) if args.email else
                   (build_router(target="host" if args.host else "lambda"), ROUTER_OUT) if args.router else (build(), OUT))
    prefix = "email-" if args.email else "router-" if args.router else ""
    key = f"papyrus-monitoring/{prefix}{digest}.zip"
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
