"""Tiny image headers for tests and specs: just enough bytes for ``share_image_check`` to read a format and a size. Not real pictures."""

from __future__ import annotations

import struct


def sample_image(image_format: str, width: int, height: int) -> bytes:
    if image_format == "png":
        return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    if image_format == "jpeg":
        return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, height, width) + b"\x03" * 10
    if image_format == "webp":
        return b"RIFF" + struct.pack("<I", 22) + b"WEBPVP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    raise ValueError(f"No sample for {image_format}")
