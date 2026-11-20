"""The Papyrus pod: a folder of Markdown notes, read and checked as a pinned, stricter profile of Vault-LD 0.5.0 (PPY-4834f3).

Level 0 is any folder of notes. Level 1 adds ``context.jsonld`` at the root and front matter (a permanent ``id``, a ``type``, facts, typed
links) on the notes the owner chooses. ``papyrus pod init``, ``id`` and ``check`` live here; the design is
``~/Projects/papyrus-local-pod-standard.md`` (section 5 and 8).

This is not ``papyrus.operator.pod_references``: that is the Kanbus-based register of JSON reference rows behind ``--backend local``, a different
thing. A pod here is files only: nothing in this package signs in, reads a site, reads Kanbus issues or publishes anything. A pod with no site
is private.
"""
