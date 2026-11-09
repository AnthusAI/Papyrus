from papyrus_cost_usage import site_usage
from papyrus_knowledge_query.lambda_handler import handler as _knowledge_query_handler

# The site's Prospectus usage sender (amplify/cost-attribution.ts sets its environment). A partial setup fails the cold start.
USAGE = site_usage()


def handler(event, context=None):
    try:
        return _knowledge_query_handler(event, context)
    finally:
        # The query embedding's tokens are recorded where the call is made; send them before the invocation returns.
        USAGE.flush()
