"""Newsletter subscriptions: double opt-in signup and the confirmation email (docs/newsletter.md).

The ``newsletter`` plugin's Lambda (``handler.handler``) is invoked directly by the CMS Next routes.
Subscriber data lives in one DynamoDB table that is not part of the content schema.
"""
