"""Guidelines as data (PPY-2a2a8a): versioned guideline documents per kind and scope, stored as a catalog row plus one S3 file, and one resolver."""
from .document import GuidelineError, KindSpec, Field, Problem, digest, kind_names, kind_spec, register_kind, slug_for, unregister_kind, validate_document
from .layering import resolve_guidelines
from .store import GuidelineStore
from .writing import resolve_writing

__all__ = ["Field", "GuidelineError", "GuidelineStore", "KindSpec", "Problem", "digest", "kind_names", "kind_spec", "register_kind", "resolve_guidelines",
           "resolve_writing", "slug_for", "unregister_kind", "validate_document"]
