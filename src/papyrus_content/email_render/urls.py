from __future__ import annotations

from urllib.parse import urljoin, urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https", "mailto", "tel"})


def absolute_url(value: str, base: str, *, schemes: frozenset[str] = ALLOWED_SCHEMES) -> str | None:
    """Resolve ``value`` against ``base``; None when the scheme is not allowed."""
    value = (value or "").strip()
    if not value:
        return None
    base = base if base.endswith("/") or "/" in urlsplit(base).path.strip("/") else base + "/"
    joined = urljoin(base, value)
    scheme = urlsplit(joined).scheme.lower()
    return joined if scheme in schemes else None
