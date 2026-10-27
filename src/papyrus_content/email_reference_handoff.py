"""Editor-selected email references enter the existing cloud router, without votes."""
from datetime import UTC, datetime
from hashlib import sha256
import re

from .monitoring import SourceItem
from .monitoring_router import email_routing_fingerprint, validate_router_config
from .reference_intake_validation import IntakeError, _actor, canonical_source_url


def queue_email_reference(store, arguments, identity, *, endpoint):
    from .monitoring_view import monitoring_email_submission

    actor = _actor(identity)
    if not isinstance(arguments, dict) or set(arguments) != {'receiptId', 'candidateIndex', 'source_uri', 'referenceId'}:
        raise IntakeError('One imported email candidate is required.')
    receipt_id, index = arguments['receiptId'], arguments['candidateIndex']
    detail = monitoring_email_submission(store, groups=['editor'], site_endpoint=endpoint, receipt_id=receipt_id)
    if 'submission' not in detail or type(index) is not int or not 0 <= index < len(detail['candidateLinks']):
        raise IntakeError('The candidate does not belong to this receipt.')
    reference_id = arguments['referenceId']
    if not isinstance(reference_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', reference_id):
        raise IntakeError('An imported Reference id is required.')
    source = canonical_source_url(arguments['source_uri'])
    link = detail['candidateLinks'][index]
    recorded = link['url']
    if link.get('resolutionStatus') == 'unresolved':
        resolution = store.get(f"EMAILRESOLVED#{receipt_id[6:]}#{index:06d}") or {}
        if (resolution.get('receiptDigest') != receipt_id[6:] or resolution.get('candidateIndex') != index
                or not isinstance(resolution.get('ttl'), int) or resolution['ttl'] <= int(datetime.now(UTC).timestamp())):
            raise IntakeError('Resolve this article before requesting predictions.')
        recorded = resolution.get('sourceUri')
    if canonical_source_url(recorded) != source:
        raise IntakeError('The URL does not match the selected receipt candidate.')
    config = validate_router_config(store.get('CONFIG#router') or {})
    publication = next(p for p in config['publications'] if p['appsyncEndpoint'] == endpoint)
    if not config['enabled'] or config['mode'] != 'live' or config['decisions'] != 'cyclotron':
        raise IntakeError('Cloud predictions are not enabled for this publication.')
    # Stable per publication/corpus/URL, so retries and duplicate receipts share one job.
    source_id = sha256(f"{endpoint}\n{publication['corpusId']}\n{source}".encode()).hexdigest()
    monitor_id = store.pk.removeprefix('MONITOR#')
    item = SourceItem(source_id, (link.get('title') or source)[:1000], source, source, None)
    now = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
    selection = {'subject': actor, 'receiptId': receipt_id, 'candidateIndex': index,
                 'publicationId': publication['publicationId'], 'referenceId': reference_id}
    discovery = {'pk': store.pk, 'sk': f'DISC#{source_id}#000001', 'monitorId': monitor_id,
                 'sourceType': 'email', 'sourceId': source_id, 'title': item.title,
                 'canonicalUrl': source, 'sourceItemUrl': source, 'sourceUrl': source,
                 'fingerprint': item.fingerprint, 'revision': 1, 'observedAt': now,
                 'eventId': f'email-reference-{source_id}', 'runId': receipt_id, 'routing': 'collected',
                 'emailTrustMode': 'data-only', 'emailDestinationPublicationIds': [publication['publicationId']],
                 'emailRoutingFingerprint': email_routing_fingerprint(config),
                 'emailProvenance': {'receiptId': receipt_id, 'inputTrust': 'untrusted-source-material',
                                     'editorSelection': selection,
                                     'sesDiagnostics': (store.get(receipt_id) or {}).get('sesDiagnostics') or {}},
                 'editorSelectedReference': selection,
                 'gsi1pk': f'ROUTING#{monitor_id}#email-references', 'gsi1sk': f'{now}#{source_id}#000001'}
    try:
        store.table.put_item(Item=discovery, ConditionExpression='attribute_not_exists(pk)')
    except Exception as error:
        if ('ConditionalCheckFailed' not in str(error)
                and getattr(error, 'response', {}).get('Error', {}).get('Code') != 'ConditionalCheckFailedException'):
            raise
        prior = store.get(discovery['sk']) or {}
        if (prior.get('canonicalUrl') != source or prior.get('emailRoutingFingerprint') != discovery['emailRoutingFingerprint']
                or (prior.get('editorSelectedReference') or {}).get('referenceId') != reference_id):
            raise IntakeError('Existing prediction request requires reconciliation.') from None
    return {'queued': True, 'sourceId': source_id, 'referenceId': reference_id}
