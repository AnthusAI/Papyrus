"""SiteConfig: the settings a tenant on the shared tier can set, as a versioned JSON schema, and the converter from a dedicated site's ``projection.json``."""

from .convert import ConversionError, from_site_config, to_site_config
from .validate import REFUSED_SETTINGS, SCHEMA, validate_site_config

__all__ = ["ConversionError", "REFUSED_SETTINGS", "SCHEMA", "from_site_config", "to_site_config", "validate_site_config"]
