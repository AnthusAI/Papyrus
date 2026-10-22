"""Bundle entry kept for the shared Python bundler, which copies ``handler.py`` to the asset root.

The Lambda's handler is ``papyrus_content.newsletter.handler.handler`` (src/papyrus_content/newsletter/handler.py).
"""

from papyrus_content.newsletter.handler import handler  # noqa: F401
