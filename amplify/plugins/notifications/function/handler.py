"""Bundle entry kept for the shared Python bundler, which copies ``handler.py`` to the asset root.

The Lambdas' handlers are ``papyrus_content.notifications.handler.{router,email,flush,ses_events}``
(src/papyrus_content/notifications/handler.py).
"""

from papyrus_content.notifications.handler import email, flush, router, ses_events  # noqa: F401
