"""Image providers: one small interface, a fake for every test and spec, and the OpenAI provider.

Nothing here runs at import. A provider is built and called only by a person on a site whose settings approve spending; the tests and specs use
``FakeProvider`` and ``OpenAIProvider`` with a fake ``post`` function, and never reach the network.
"""
from __future__ import annotations

import base64
import json
import os
import struct
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Callable, Protocol


@dataclass(frozen=True)
class ProviderRequest:
    prompt: str
    model: str
    width: int = 1024
    height: int = 1024
    quality: str | None = None
    speed: str = "standard"


@dataclass(frozen=True)
class ProviderImage:
    data: bytes
    media_type: str
    width: int
    height: int
    input_tokens: int = 0
    output_tokens: int = 0
    provider_ref: str = ""


class ProviderFailure(Exception):
    """The provider refused or failed. ``code`` is ``provider_failed`` or ``provider_busy``."""

    def __init__(self, code: str, message: str, *, retryable: bool = True, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.code, self.message, self.retryable, self.retry_after_seconds = code, message, retryable, retry_after_seconds


class ImageProvider(Protocol):
    name: str

    def generate(self, request: ProviderRequest) -> ProviderImage: ...


def tiny_png(width: int = 1, height: int = 1) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + b"\x1f\x2a\x44" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


@dataclass
class FakeProvider:
    """Answers with a small valid picture. ``failures`` is a list consumed one per call: a ProviderFailure is raised, None lets the call through."""
    name: str = "fake"
    failures: list = field(default_factory=list)
    requests: list = field(default_factory=list)

    def generate(self, request: ProviderRequest) -> ProviderImage:
        self.requests.append(request)
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None:
            raise failure
        return ProviderImage(tiny_png(), "image/png", 1, 1, input_tokens=40, output_tokens=1000, provider_ref=f"fake-{len(self.requests)}")


Post = Callable[[str, dict, dict], tuple[int, dict, dict]]


def _urllib_post(url: str, headers: dict, body: dict) -> tuple[int, dict, dict]:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.status, dict(response.headers), json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read())
        except ValueError:
            payload = {}
        return error.code, dict(error.headers), payload


def size_for(width: int, height: int) -> str:
    """One of the three sizes every OpenAI image model accepts, by the shape asked for."""
    if width > height:
        return "1536x1024"
    if height > width:
        return "1024x1536"
    return "1024x1024"


@dataclass
class OpenAIProvider:
    """OpenAI's image generations endpoint. ``api_key`` is called for each request and is never stored or logged. ``post`` is replaceable for tests."""
    api_key: Callable[[], str]
    post: Post = _urllib_post
    name: str = "openai"
    endpoint: str = "https://api.openai.com/v1/images/generations"

    def generate(self, request: ProviderRequest) -> ProviderImage:
        body = {"model": request.model, "prompt": request.prompt, "n": 1, "size": size_for(request.width, request.height)}
        if request.quality:
            body["quality"] = request.quality
        status, headers, payload = self.post(self.endpoint, {"Authorization": f"Bearer {self.api_key()}"}, body)
        if status == 429:
            raise ProviderFailure("provider_busy", "OpenAI is rate limiting image requests.", retry_after_seconds=int(headers.get("Retry-After") or 30))
        if status >= 500:
            raise ProviderFailure("provider_failed", f"OpenAI answered {status}.")
        if status >= 400:
            message = (payload.get("error") or {}).get("message") or f"OpenAI answered {status}."
            raise ProviderFailure("provider_failed", message, retryable=False)
        item = (payload.get("data") or [{}])[0]
        if not item.get("b64_json"):
            raise ProviderFailure("provider_failed", "OpenAI answered without a picture.", retryable=False)
        usage = payload.get("usage") or {}
        width, _, height = body["size"].partition("x")
        return ProviderImage(base64.b64decode(item["b64_json"]), "image/png", int(width), int(height), int(usage.get("input_tokens") or 0),
                             int(usage.get("output_tokens") or 0), str(payload.get("id") or ""))


def openai_from_environment() -> OpenAIProvider:
    """The provider a person runs on their own machine: the key comes from OPENAI_API_KEY at the moment of a call."""
    def key() -> str:
        value = os.environ.get("OPENAI_API_KEY")
        if not value:
            raise ProviderFailure("provider_failed", "OPENAI_API_KEY is not set.", retryable=False)
        return value
    return OpenAIProvider(api_key=key)
