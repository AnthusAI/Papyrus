"""Sending the confirmation email through Amazon SES (SESv2, Simple content with HTML and text)."""

from __future__ import annotations

from email.header import Header
from typing import Any


def format_sender(from_name: str, from_address: str) -> str:
    """``"Name" <address>``; a non-ASCII name is RFC 2047 encoded, quotes and line breaks never get through."""
    name = " ".join(from_name.replace("\r", " ").replace("\n", " ").split())
    if not name:
        return from_address
    if name.isascii():
        quoted = name.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{quoted}" <{from_address}>'
    return f"{Header(name, 'utf-8').encode()} <{from_address}>"


class Mailer:
    def __init__(self, *, from_name: str, from_address: str, configuration_set: str, site_id: str, client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("sesv2")
        self.client = client
        self.sender = format_sender(from_name, from_address)
        self.configuration_set = configuration_set
        self.site_id = site_id

    def send_confirmation(self, *, to: str, subject: str, html: str, text: str) -> str:
        response = self.client.send_email(
            FromEmailAddress=self.sender,
            Destination={"ToAddresses": [to]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html, "Charset": "UTF-8"}, "Text": {"Data": text, "Charset": "UTF-8"}},
                }
            },
            ConfigurationSetName=self.configuration_set,
            EmailTags=[{"Name": "site", "Value": self.site_id}, {"Name": "kind", "Value": "confirm"}],
        )
        return str(response.get("MessageId", ""))
