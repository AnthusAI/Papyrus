from papyrus_knowledge_query.reference_words import stream_handler


def handler(event, context=None):
    return stream_handler(event, context)
