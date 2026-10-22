"""Current private database guidance at classification and editing boundaries."""
from copy import deepcopy
from dataclasses import replace

from .editorial_context import _digest, build_context, resolve_editorial_context

CONTEXT_HASHES = '_papyrus_editorial_context_hashes'


def checked_context(pack, *, section=None, publication=None, mode='cloud'):
    if (not isinstance(pack, dict) or pack.get('sourceMode') != mode
            or pack.get('rendererVersion') != 'editorial-context/v1'
            or not pack.get('text') or not pack.get('contextHash')):
        raise ValueError('Current scoped editorial context is required')
    scope = pack.get('scope', {})
    # The section may have been asked for by slug or name (or matched nothing); the scope says which.
    if section not in (scope.get('sectionId'), scope.get('requestedSection')):
        raise ValueError('Editorial context section mismatch')
    if publication is not None and pack.get('publication', {}).get('key') != publication:
        raise ValueError('Editorial context publication mismatch')
    material = {key: value for key, value in pack.items() if key not in ('contextHash', 'resolvedAt')}
    if pack['contextHash'] != _digest(material):
        raise ValueError('Editorial context fingerprint mismatch')
    return pack


class ContextualDecisionModel:
    """Keep policy outside learned rubrics and include its hash in item identity.

    Each request re-reads its database contexts. A change after preparation
    fails before provider transmission; a newly prepared item invalidates the
    engine's stable-decision cache. Each classifier sees only its own context.
    """
    def __init__(self, model, resolve_contexts):
        self.model, self.resolve_contexts = model, resolve_contexts

    @property
    def model_identity(self):
        return self.model.model_identity

    def _contexts(self):
        contexts = self.resolve_contexts()
        if not contexts:
            raise ValueError('Current editorial context is required for every classifier')
        for pack in contexts.values():
            checked_context(pack, section=pack.get('scope', {}).get('sectionId'))
        return contexts

    def verify_context(self):
        """Preflight required database policy before a sweep mutates any state."""
        self._contexts()

    def prepare(self, item):
        from decision_flywheel import Item
        if CONTEXT_HASHES in item.values:
            raise ValueError('Editorial context identities are supplied only by the trusted host')
        contexts = self._contexts()
        return Item(item.id, {**item.values, CONTEXT_HASHES: {key: p['contextHash'] for key, p in contexts.items()}})

    async def classify_many(self, configurations, target, training, **kwargs):
        contexts = self._contexts()
        hashes = {key: pack['contextHash'] for key, pack in contexts.items()}
        if target.values.get(CONTEXT_HASHES) != hashes:
            raise ValueError('Editorial context changed; prepare the item again before deciding')
        if not set(configurations) <= set(contexts):
            raise ValueError('Classifier is outside the resolved editorial context')
        scoped = {key: replace(config, rubric=(
            'Current database editorial guidance governs this classifier. '
            'Surface conflicts with supplementary learned criteria.\n'
            + contexts[key]['text'] + '\nSupplementary learned criteria:\n' + config.rubric))
            for key, config in configurations.items()}
        return await self.model.classify_many(scoped, target, training, **kwargs)


def classification_model(model, client, steering, sections=()):
    """Bind a publication's existing model to live private records, never seeds."""
    from .site_cyclotron import enabled_sections_in_order, section_fit_classifier_id, section_selector_classifier_id
    ordered = enabled_sections_in_order(sections)

    def resolve():
        def context(section=None):
            return resolve_editorial_context(client, endpoint=client.endpoint, section_id=section)
        if not ordered:
            return {steering['relevanceCyclotron']['classifierId']: context()}
        packs = {section_fit_classifier_id(row['id']): context(row['id']) for row in ordered}
        if len(ordered) > 1:
            first = next(iter(packs.values()))
            publication_entries = [e for e in first['entries'] if e['scope'] == 'publication']
            entries = list(publication_entries)
            for pack in packs.values():
                if pack['publication'] != first['publication']:
                    raise ValueError('Section context publication changed during assembly')
                if [e for e in pack['entries'] if e['scope'] == 'publication'] != publication_entries:
                    raise ValueError('Publication policy changed during section context assembly')
                entries.extend(e for e in pack['entries'] if e['scope'] == 'section')
            identifier = section_selector_classifier_id([row['id'] for row in ordered])
            packs[identifier] = build_context(first['publication'], {'sectionId': None, 'sectionIds': [row['id'] for row in ordered]},
                                               entries, mode='cloud')
        return packs
    return ContextualDecisionModel(model, resolve)


def editing_pack(store, section, settings):
    return editing_pack_and_context(store, section, settings)[0]


def editing_pack_and_context(store, section, settings):
    """The pack Humanus checks with, and the context it was built from (which says what publication doctrine is missing)."""
    from .editorial_checks import compose_pack
    context = checked_context(store.get_editorial_context(section), section=section,
                              mode=getattr(store, 'context_mode', 'cloud'))
    pack = deepcopy(compose_pack(store.list_policies(), section, settings))
    pack['version'] += '-' + context['contextHash']
    pack['guidance'] = context['text'] + '\n' + pack.get('guidance', '')
    for policy in pack['policies']:
        for detector in policy['detectors']:
            if detector.get('lane') == 'classifier':
                question = detector['question']
                question['instructions'] = (context['text'] + '\nApply this private operating guidance to the target only.\n'
                                            + question['instructions'])
    return pack, context
