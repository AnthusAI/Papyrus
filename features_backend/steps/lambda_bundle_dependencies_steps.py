from __future__ import annotations

import ast
import re
import sys
from importlib import metadata
from pathlib import Path

from behave import given, then, when
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "src"

# Bundle name -> the handler, the requirements file, and the TypeScript list a site repository bundles from.
BUNDLES = {
    "content-actions": {
        "handler": "amplify/functions/content-actions/handler.py",
        "requirements": "amplify/functions/content-actions/requirements.txt",
        "typescript": ("amplify/functions/content-actions/resource.ts", "contentActionsRequirements"),
    },
    "renditions": {
        "handler": "amplify/functions/renditions/handler.py",
        "requirements": "amplify/functions/renditions/requirements.txt",
        "typescript": ("amplify/publication/renditions-function.ts", "renditionsRequirements"),
    },
}

# The Lambda Python runtime provides these, so no bundle lists them.
PROVIDED_BY_THE_RUNTIME = {"boto3", "botocore"}
OUR_OWN_MODULES = {"papyrus", "papyrus_content", "papyrus_knowledge_query", "papyrus_newsroom", "papyrus_cost_usage", "papyrus_web"}
# The render code path: every import in these packages counts, including the ones inside functions.
RENDER_CODE_PATH = "projection"
# The Lambda's own platform, for requirement markers.
LAMBDA_MARKERS = {"sys_platform": "linux", "platform_system": "Linux", "platform_machine": "aarch64", "extra": ""}


def requirement_names(lines: list[str]) -> list[str]:
    return [canonicalize_name(Requirement(line).name) for line in lines]


def requirement_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.strip().startswith("#")]


def typescript_list(path: Path, name: str) -> list[str]:
    match = re.search(rf"{name} = \[(.*?)\];", path.read_text(), re.S)
    assert match, f"{path} has no {name} list"
    return re.findall(r'"([^"]+)"', match.group(1))


def own_module_file(name: str) -> Path | None:
    base = SOURCE.joinpath(*name.split("."))
    if base.with_suffix(".py").exists():
        return base.with_suffix(".py")
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    return None


def import_time_nodes(tree: ast.Module):
    """The statements that run when a module loads: module level, inside ``if``, and inside a ``try`` that does not guard an optional import."""
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, ast.If):
            stack += node.body + node.orelse
        elif isinstance(node, ast.Try):
            guards_optional_import = any(h.type is not None and "ImportError" in ast.dump(h.type) for h in node.handlers)
            if not guards_optional_import:
                stack += node.body


def imported_names(path: Path, *, everywhere: bool) -> list[str]:
    tree = ast.parse(path.read_text())
    nodes = ast.walk(tree) if everywhere else import_time_nodes(tree)
    names: list[str] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative = path.relative_to(SOURCE).parts
                package = relative[:-1]
                module = ".".join(list(package[: len(package) - (node.level - 1)]) + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            names.append(module)
            names += [f"{module}.{alias.name}" for alias in node.names]
    return names


def third_party_imports(handler: Path) -> dict[str, set[str]]:
    """Top-level third-party module name -> the files (relative to the repository) that import it, on the handler's import path."""
    found: dict[str, set[str]] = {}
    seen: set[Path] = set()
    pending = [handler]
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        everywhere = RENDER_CODE_PATH in path.relative_to(REPO_ROOT).parts
        for name in imported_names(path, everywhere=everywhere):
            top = name.split(".")[0]
            local = own_module_file(name)
            if local is not None:
                pending.append(local)
            elif top in OUR_OWN_MODULES or top in sys.stdlib_module_names or top == "__future__":
                continue
            elif (path.parent / f"{top}.py").exists() or (path.parent / top).exists():
                continue  # the handler's sibling file
            else:
                found.setdefault(top, set()).add(str(path.relative_to(REPO_ROOT)))
    return found


def providing_package(module: str) -> str | None:
    owners = metadata.packages_distributions().get(module)
    return canonicalize_name(owners[0]) if owners else None


def bundle_closure(names: list[str]) -> set[str]:
    """The packages pip installs for these requirements: each one and everything it requires, markers read for the Lambda's platform."""
    closure: set[str] = set()
    pending = list(names)
    while pending:
        name = pending.pop()
        if name in closure:
            continue
        closure.add(name)
        try:
            requires = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            continue
        for line in requires:
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate(LAMBDA_MARKERS):
                pending.append(canonicalize_name(requirement.name))
    return closure


def missing_packages(context) -> dict[str, set[str]]:
    in_bundle = bundle_closure(requirement_names(context.requirement_lines))
    missing: dict[str, set[str]] = {}
    for module, files in context.third_party.items():
        if module in PROVIDED_BY_THE_RUNTIME:
            continue
        package = providing_package(module)
        if package is None:
            missing.setdefault(f"(no installed package provides the module {module!r})", set()).update(files)
        elif package not in in_bundle:
            missing.setdefault(package, set()).update(files)
    return missing


def failure_message(context, missing: dict[str, set[str]]) -> str:
    requirements = context.bundle["requirements"]
    typescript = context.bundle["typescript"][0]
    lines = [f"The {context.bundle_name} Lambda bundle lacks packages its code imports; the deploy would fail with 'No module named'."]
    for package, files in sorted(missing.items()):
        lines.append(f"  {package} is imported by {', '.join(sorted(files))}")
    lines.append(f"Add each to {requirements} and to the list in {typescript}.")
    return "\n".join(lines)


@given('the "{name}" Lambda bundle and its handler')
def step_bundle(context, name):
    context.bundle_name = name
    context.bundle = BUNDLES[name]
    context.requirement_lines = requirement_lines(REPO_ROOT / context.bundle["requirements"])


@given('the requirements leave out "{package}"')
def step_leave_out(context, package):
    context.requirement_lines = [line for line in context.requirement_lines if canonicalize_name(Requirement(line).name) != canonicalize_name(package)]


@when("the third-party modules on the handler's import path are collected")
def step_collect(context):
    context.third_party = third_party_imports(REPO_ROOT / context.bundle["handler"])


@then("every package that provides them is in the bundle")
def step_all_in_bundle(context):
    missing = missing_packages(context)
    assert not missing, failure_message(context, missing)


@then('the standard front end\'s import of "{module}" is among them')
def step_front_end_imports(context, module):
    files = context.third_party.get(module, set())
    assert any("projection/standard" in file for file in files), f"the standard front end no longer imports {module}; found {sorted(context.third_party)}"


@then('the package "{package}" is in the bundle')
def step_package_in_bundle(context, package):
    assert canonicalize_name(package) in bundle_closure(requirement_names(context.requirement_lines)), (
        f"{package} is not in the {context.bundle_name} bundle ({context.bundle['requirements']})"
    )


@given('the package "{package}" that the bundle installs')
def step_package_installed(context, package):
    context.package = package


@then('its files include the locale data for "{first}", "{second}" and "{third}"')
def step_locale_data(context, first, second, third):
    files = {str(file) for file in metadata.files(context.package) or []}
    missing = [code for code in (first, second, third) if f"babel/locale-data/{code}.dat" not in files]
    assert not missing, f"{context.package} ships no locale data for {missing}; dates in those languages would not print"


@then('the check fails naming the package "{package}" and the file "{path}"')
def step_check_fails(context, package, path):
    missing = missing_packages(context)
    assert canonicalize_name(package) in missing, f"expected {package} to be reported missing, got {sorted(missing)}"
    message = failure_message(context, missing)
    assert canonicalize_name(package) in message and path in message, message


@then("the requirements file and the TypeScript list name the same packages")
def step_lists_agree(context):
    source, name = context.bundle["typescript"]
    listed = sorted(typescript_list(REPO_ROOT / source, name))
    pinned = sorted(context.requirement_lines)
    assert listed == pinned, f"{context.bundle['requirements']} and {name} in {source} differ: {sorted(set(listed) ^ set(pinned))}"
