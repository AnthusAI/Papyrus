from papyrus_knowledge_query.reference_words import stream_handler


def handler(event, context=None):
    """The word index, then the change feed: where the Reference stream already has two readers the feed is not a third, this reader passes it the batch and
    reports what the feed could not do (papyrus_content.change_feed_relay; PPY-9b9e64)."""
    from papyrus_content.change_feed_relay import relay

    failures = {item["itemIdentifier"]: item for item in [*stream_handler(event, context)["batchItemFailures"], *relay(event)]}
    return {"batchItemFailures": list(failures.values())}
