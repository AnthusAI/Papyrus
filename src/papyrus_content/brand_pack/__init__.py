"""BrandPack: how a shared-tier site may look, as a versioned JSON schema plus a validator for contrast, colour-safe pairs and fonts."""

from .validate import POLICY, SCHEMA, validate_brand_pack

__all__ = ["POLICY", "SCHEMA", "validate_brand_pack"]
