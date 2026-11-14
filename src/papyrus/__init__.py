"""Unified Papyrus CLI package."""

from importlib.metadata import PackageNotFoundError, version as _distribution_version

SOURCE_CHECKOUT_VERSION = "0.0.0+source"


def installed_version(distribution: str = "papyrus-newsroom", lookup=_distribution_version) -> str:
    """The installed distribution's version; a source checkout with no installed distribution gets a marked fallback."""
    try:
        return lookup(distribution)
    except PackageNotFoundError:
        return SOURCE_CHECKOUT_VERSION


__version__ = installed_version()
