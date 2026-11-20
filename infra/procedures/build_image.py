#!/usr/bin/env python3
"""Build the procedure runner image for arm64 Lambda and push it to ECR, once per set of inputs. Run by the release (infra/pipeline/stack_deploy.py), never by hand.

  python3 infra/procedures/build_image.py            # prints "CodeKey <registry>/<repository>@<digest>" (the pipeline's build protocol)
  python3 infra/procedures/build_image.py --tag      # prints the tag only, builds nothing

The tag is `src-` plus a hash of everything the Dockerfile copies (pyproject.toml, README.md, LICENSE*, src/, corpora/) and the Dockerfile itself, taken from
the files Git tracks, so the image cannot go stale: a change to the code is a new tag, and an unchanged tree reuses the image already in the repository.
Tags are immutable in the repository. The repository itself is the `RunnerRepository` of papyrus-procedure-runner.yaml. Asserts that the caller's account is the AWS_ACCOUNT_ID the release passes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REGION = "us-east-1"
REPOSITORY = "papyrus-procedure-runner"
DOCKERFILE = "infra/procedures/Dockerfile"
INPUTS = ("pyproject.toml", "README.md", "LICENSE", "src", "corpora", DOCKERFILE)


def tracked_inputs() -> list[str]:
    done = subprocess.run(["git", "ls-files", "-z", "--", *INPUTS], cwd=ROOT, capture_output=True, text=True, check=True)
    return sorted(name for name in done.stdout.split("\0") if name)


def image_tag(files: list[str] | None = None) -> str:
    digest = hashlib.sha256()
    for name in files if files is not None else tracked_inputs():
        digest.update(name.encode() + b"\0" + hashlib.sha256((ROOT / name).read_bytes()).digest())
    return "src-" + digest.hexdigest()[:24]


def aws(*args: str) -> dict:
    done = subprocess.run(["aws", *args, "--region", REGION, "--output", "json"], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout).strip())
    return json.loads(done.stdout) if done.stdout.strip() else {}


def existing_digest(tag: str) -> str | None:
    try:
        return aws("ecr", "describe-images", "--repository-name", REPOSITORY, "--image-ids", f"imageTag={tag}")["imageDetails"][0]["imageDigest"]
    except RuntimeError as error:
        if "ImageNotFoundException" in str(error):
            return None
        raise


def main(argv: list[str]) -> int:
    tag = image_tag()
    if argv == ["--tag"]:
        print(tag)
        return 0
    account = aws("sts", "get-caller-identity")["Account"]
    if account != os.environ.get("AWS_ACCOUNT_ID"):
        print("Refusing: the caller's account is not the AWS_ACCOUNT_ID the release was given", file=sys.stderr)
        return 2
    registry = f"{account}.dkr.ecr.{REGION}.amazonaws.com"
    digest = existing_digest(tag)
    if digest is None:
        password = subprocess.run(["aws", "ecr", "get-login-password", "--region", REGION], capture_output=True, text=True, check=True).stdout
        subprocess.run(["docker", "login", "--username", "AWS", "--password-stdin", registry], input=password, text=True, check=True, capture_output=True)
        subprocess.run(["docker", "buildx", "build", "--platform", "linux/arm64", "--provenance=false", "-f", str(ROOT / DOCKERFILE), "-t", f"{registry}/{REPOSITORY}:{tag}",
                        "--push", str(ROOT)], check=True, stdout=sys.stderr)
        digest = existing_digest(tag)
    print(f"CodeKey {registry}/{REPOSITORY}@{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
