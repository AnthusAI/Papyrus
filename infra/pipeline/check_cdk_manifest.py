#!/usr/bin/env python3
"""Refuse a synthesized CDK app that holds anything but the one expected CloudFormation stack.

    check_cdk_manifest.py --out cdk.out --expect NAME

Reads <out>/manifest.json and counts the artifacts of type aws:cloudformation:stack. Exit 0 only when there is exactly one and its
name is NAME; exit 2 with a plain message otherwise (none, several, another name, a missing or unreadable manifest). The app-shell
workflow runs this before any AWS credential exists, so a synth that names another stack (the account baseline, say) never deploys.
Nothing here calls AWS.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STACK_TYPE = "aws:cloudformation:stack"


def check(out: Path, expect: str) -> str | None:
    """Return None when the assembly is acceptable, else the reason it is not."""
    manifest = out / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return f"{manifest} does not exist; the synth produced no cloud assembly"
    except (OSError, ValueError) as exc:
        return f"{manifest} cannot be read as JSON: {exc}"
    artifacts = data.get("artifacts") if isinstance(data, dict) else None
    if not isinstance(artifacts, dict):
        return f"{manifest} has no artifacts object"
    # The CloudFormation stack name is the artifact's `properties.stackName`; the artifact key is the construct id, which differs
    # (found on the first Humorus synth: key AmplifyAppShell-the-hallucinator, stackName humorus-app-shell).
    names = sorted(
        (art.get("properties") or {}).get("stackName") or name
        for name, art in artifacts.items()
        if isinstance(art, dict) and art.get("type") == STACK_TYPE
    )
    if not names:
        return f"the manifest holds no CloudFormation stack; expected exactly one named {expect}"
    if len(names) > 1:
        return f"the manifest holds {len(names)} CloudFormation stacks ({', '.join(names)}); expected exactly one named {expect}"
    if names[0] != expect:
        return f"the manifest's only CloudFormation stack is named {names[0]}; expected {expect}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="the synthesized cloud assembly directory (cdk.out)")
    parser.add_argument("--expect", required=True, help="the one CloudFormation stack name that may be deployed")
    args = parser.parse_args(argv)
    problem = check(Path(args.out), args.expect)
    if problem:
        print(f"::error::{problem}", file=sys.stderr)
        print(f"Refusing to deploy: {problem}", file=sys.stderr)
        return 2
    print(f"The cloud assembly holds exactly one stack, {args.expect}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
