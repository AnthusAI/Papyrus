"""Operator tool: send one tagged test message through a site's configuration set, to drive a live check.

    python -m papyrus_content.newsletter simulate --site-id shipped --from-address <on the sending domain> \\
        --from-name Shipped --outcome bounce --hid <32 hex> [--issue <id>] [--list <id>]

``--outcome`` picks an Amazon SES mailbox simulator address (success, bounce, complaint, ooto, suppressionlist), so no real
inbox is involved; ``--to`` sends to any other address instead. The message carries the tags the event handler maps back
with (``site``, ``sub``, and optionally ``issue`` and ``list``) and ``kind=test``. It needs AWS credentials that may call
``ses:SendEmail`` on the site identity and configuration set. ``--dry-run`` prints the request and sends nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Sequence

from .mailer import format_sender

OUTCOMES = ("success", "bounce", "complaint", "ooto", "suppressionlist")
SIMULATOR_DOMAIN = "simulator.amazonses.com"
HID = re.compile(r"[0-9a-f]{32}")
TAG_VALUE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def simulator_address(outcome: str) -> str:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
    return outcome + "@" + SIMULATOR_DOMAIN


def build_request(args: argparse.Namespace) -> dict[str, Any]:
    if not HID.fullmatch(args.hid):
        raise ValueError("--hid must be a 32 character lowercase hex subscriber id")
    tags = [("site", args.site_id), ("sub", args.hid), ("kind", "test")]
    tags += [(name, value) for name, value in (("issue", args.issue), ("list", args.list)) if value]
    for name, value in tags:
        if not TAG_VALUE.fullmatch(value):
            raise ValueError(f"tag {name} must be letters, digits, underscore, hyphen or dot")
    return {
        "FromEmailAddress": format_sender(args.from_name, args.from_address),
        "Destination": {"ToAddresses": [args.to or simulator_address(args.outcome)]},
        "Content": {
            "Simple": {
                "Subject": {"Data": "[Test] Papyrus newsletter delivery check", "Charset": "UTF-8"},
                "Body": {"Text": {"Data": "A test message from the Papyrus newsletter plugin. No action needed.", "Charset": "UTF-8"}},
            }
        },
        "ConfigurationSetName": args.configuration_set or f"papyrus-{args.site_id}",
        "EmailTags": [{"Name": name, "Value": value} for name, value in tags],
    }


def main(argv: Sequence[str] | None = None, client: Any = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m papyrus_content.newsletter", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    simulate = commands.add_parser("simulate", help="send one tagged test message")
    simulate.add_argument("--site-id", required=True)
    simulate.add_argument("--from-address", required=True)
    simulate.add_argument("--from-name", required=True)
    simulate.add_argument("--configuration-set", default="")
    simulate.add_argument("--outcome", choices=OUTCOMES, default="success")
    simulate.add_argument("--to", default="")
    simulate.add_argument("--hid", required=True)
    simulate.add_argument("--issue", default="")
    simulate.add_argument("--list", default="")
    simulate.add_argument("--region", default="")
    simulate.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = build_request(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps(request, indent=2))
        return 0
    if client is None:
        import boto3

        client = boto3.client("sesv2", **({"region_name": args.region} if args.region else {}))
    response = client.send_email(**request)
    print(json.dumps({"messageId": response.get("MessageId"), "to": request["Destination"]["ToAddresses"][0]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
