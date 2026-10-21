#!/usr/bin/env python3
"""Build the deterministic collector zip; optionally upload it by content hash.

  python3 infra/monitoring/build.py                 # build only, print SHA256 and S3 key
  python3 infra/monitoring/build.py --upload BUCKET # also upload (needs AWS_PROFILE; asserts the account)

The zip holds only the modules the Lambda imports. Prints no secrets.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MODULES = ("__init__.py", "monitoring.py", "monitoring_cloud.py")
ACCOUNT = "712236451410"
OUT = Path(__file__).resolve().parent / "dist" / "papyrus-monitoring.zip"


def build(out: Path = OUT) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(MODULES):
            info = zipfile.ZipInfo(f"papyrus_content/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (ROOT / "src" / "papyrus_content" / name).read_bytes())
    return hashlib.sha256(out.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", metavar="BUCKET")
    args = parser.parse_args()
    digest = build()
    key = f"papyrus-monitoring/{digest}.zip"
    print(f"SHA256 {digest}\nCodeKey {key}\nSize {OUT.stat().st_size} bytes")
    if args.upload:
        account = subprocess.run(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
                                 check=True, capture_output=True, text=True).stdout.strip()
        if account != ACCOUNT:
            print(f"Refusing to upload: caller account is not {ACCOUNT}", file=sys.stderr)
            return 2
        subprocess.run(["aws", "s3", "cp", str(OUT), f"s3://{args.upload}/{key}", "--only-show-errors"], check=True)
        print(f"Uploaded s3://{args.upload}/{key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
