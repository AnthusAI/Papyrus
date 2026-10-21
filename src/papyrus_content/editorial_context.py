"""Resolve private editorial policy once; render the same contract for agents and workers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from .env import graphql_endpoint, load_dotenv
from .newsroom_doctrine import DOCTRINE_DEFINITION_BY_KIND

PRECEDENCE = ['publication', 'section', 'assignment']


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _check_tenant(client, record: dict) -> None:
    # Absence of tenant configuration must not mean permission to mix tenants.
    if (record.get('tenantId') or None) != (getattr(client, 'tenant_id', None) or None):
        raise ValueError('Editorial record tenant does not match the configured authoring scope.')


def current_record(rows: list[dict], label: str) -> dict:
    current = [row for row in rows if row.get('versionState') == 'current']
    if len(current) != 1:
        raise ValueError(f'{label}: expected exactly one current record, found {len(current)}.')
    return current[0]


def _body(record: dict) -> str:
    if record.get('bodyMarkus'):
        return str(record['bodyMarkus']).strip()
    body = record.get('body') or []
    return '\n\n'.join(str(part).strip() for part in body if str(part).strip())


def _entry(scope: str, kind: str, text: str, record: dict, **source: Any) -> dict:
    return {'scope': scope, 'kind': kind, 'text': text, 'source': {
        **{key: record.get(key) for key in ('id', 'lineageId', 'versionNumber', 'updatedAt', 'contentHash')},
        'sha256': hashlib.sha256(text.encode()).hexdigest(), **source,
    }}


def build_context(publication: dict, scope: dict, entries: list[dict], *, mode: str,
                  warnings: list[str] | None = None, max_characters: int = 0) -> dict:
    warnings = list(warnings or [])
    lines = [f"Editorial context: {publication['key']}", f'Source: {mode}',
             'Precedence: publication > section > assignment. Surface conflicts; narrower instructions do not silently override publication policy.',
             'Private operating guidance; not evidence or reader-facing copy.']
    for entry in entries:
        lines.extend(['', f"## {entry['scope']}: {entry['kind']}", entry['text']])
    text = '\n'.join(lines) + '\n'
    if max_characters < 0:
        raise ValueError('Editorial context budget must be nonnegative.')
    if max_characters and len(text) > max_characters:
        raise ValueError(f'Editorial context budget {max_characters} cannot hold {len(text)} required characters; policy was not truncated.')
    payload = {'schemaVersion': 1, 'rendererVersion': 'editorial-context/v1', 'publication': publication,
               'scope': scope, 'sourceMode': mode, 'precedence': PRECEDENCE,
               'entries': entries, 'sources': [entry['source'] for entry in entries],
               'warnings': warnings, 'text': text, 'totalCharacters': len(text)}
    payload['contextHash'] = _digest(payload)
    payload['resolvedAt'] = datetime.now(timezone.utc).isoformat()
    return payload


def hosted_publication(client, requested_key: str | None = None) -> dict:
    """The publication this backend serves: its one canonical KnowledgeCorpus (data, not repo configuration).

    A requested key is only an assertion about which publication the caller believes it is talking to.
    """
    corpora = client.list_by_index('knowledgeCorporaByRoleAndName', 'canonical')
    if (len(corpora) != 1 or corpora[0].get('role') != 'canonical' or not str(corpora[0].get('name') or '').strip()
            or not str(corpora[0].get('id') or '').startswith('knowledge-corpus-')):
        raise ValueError('The hosted backend has no single canonical corpus; missing or ambiguous publication binding. '
                         'On a fresh backend create it with `papyrus publication init --key <key> --name <name>`.')
    key = corpora[0]['id'].removeprefix('knowledge-corpus-')
    if requested_key and requested_key != key:
        raise ValueError(f'Requested publication {requested_key} does not match the hosted canonical corpus {key}; publication binding mismatch.')
    return {'key': key, 'name': corpora[0]['name'], 'corpusId': corpora[0]['id'],
            'tenantId': getattr(client, 'tenant_id', None)}


def resolve_editorial_context(client, *, endpoint: str, publication_key: str | None = None,
                              section_id: str | None = None, story_lineage_id: str | None = None,
                              assignment_id: str | None = None, max_characters: int = 0) -> dict:
    if not endpoint:
        raise ValueError('An endpoint is required for hosted editorial context.')
    publication = hosted_publication(client, publication_key)
    entries = []
    warnings = []
    assignment = None
    if assignment_id:
        assignment = client.get_record('Assignment', assignment_id)
        if not assignment:
            raise ValueError(f'Assignment not found: {assignment_id}')
        assigned_story = assignment.get('itemLineageId')
        if story_lineage_id and assigned_story and story_lineage_id != assigned_story:
            raise ValueError('Requested story conflicts with assignment story lineage.')
        story_lineage_id = story_lineage_id or assigned_story
        assigned_section = assignment.get('sectionKey') or assignment.get('sectionId')
        if section_id and assigned_section and section_id != assigned_section:
            raise ValueError('Requested section conflicts with assignment section.')
        section_id = section_id or assigned_section
        warnings.append('Assignment policy snapshots are ignored; current publication and section records govern. Surface any conflicting assignment instructions.')
    if story_lineage_id:
        versions = client.list_by_index('itemsByLineageAndVersion', story_lineage_id)
        if not versions:
            raise ValueError(f'Story not found: {story_lineage_id}')
        story = max(versions, key=lambda row: int(row.get('versionNumber') or 0))
        _check_tenant(client, story)
        if section_id and story.get('section') and section_id != story['section']:
            raise ValueError('Requested section conflicts with story section.')
        section_id = section_id or story.get('section')
    for kind, definition in DOCTRINE_DEFINITION_BY_KIND.items():
        rows = client.list_by_index('itemBySlug', definition['slug'])
        rows = [row for row in rows if row.get('type') == 'doctrine' and row.get('status') == 'private']
        record = current_record(rows, f'Publication {kind}')
        _check_tenant(client, record)
        text = _body(record)
        if not text:
            raise ValueError(f'Required publication {kind} is empty.')
        entries.append(_entry('publication', kind, text, record))
    if section_id:
        section = client.get_record('NewsroomSection', section_id)
        if not section:
            raise ValueError(f'Requested section not found: {section_id}')
        _check_tenant(client, section)
        _section_entries(entries, warnings, section)
    if assignment:
        if getattr(client, 'tenant_id', None) and not (story_lineage_id or section_id):
            raise ValueError('A tenant assignment needs a scoped story or section to establish its publication.')
        from .model_attachments import download_attachment_buffer
        attachments = client.list_by_index('modelAttachmentsByOwnerRoleAndSortKey', assignment['id'])
        found_brief = False
        for role, kind in [('assignment_brief', 'brief'), ('assignment_instructions', 'instructions')]:
            matching = [row for row in attachments if row.get('role') == role and row.get('status') != 'deleted']
            if len(matching) > 1:
                raise ValueError(f'Ambiguous assignment {kind} attachments.')
            if matching:
                if matching[0].get('ownerKind') != 'assignment' or matching[0].get('ownerId') != assignment['id']:
                    raise ValueError('Assignment attachment owner does not match the requested scope.')
                content = download_attachment_buffer(client, matching[0])
                if content is None:
                    raise ValueError(f'Assignment {kind} attachment has no storage path.')
                text = content.decode('utf-8').strip()
                if not text:
                    raise ValueError(f'Assignment {kind} attachment is empty.')
                entries.append(_entry('assignment', kind, text, matching[0]))
                found_brief = found_brief or kind == 'brief'
        if not found_brief and assignment.get('summary'):
            entries.append(_entry('assignment', 'brief', assignment['summary'], assignment))
            warnings.append('No assignment brief attachment exists; the Assignment summary is supplied as its brief.')
    return build_context({**publication, 'endpoint': endpoint},
                         {'sectionId': section_id, 'storyLineageId': story_lineage_id, 'assignmentId': assignment_id},
                         entries, mode='cloud', warnings=warnings, max_characters=max_characters)


def _section_entries(entries: list, warnings: list, section: dict) -> None:
    for kind, key in [('mission', 'editorialMission'), ('policy', 'editorialPolicy'),
                      ('guidance', 'assignmentGuidance'), ('kill criteria', 'killCriteria')]:
        value = str(section.get(key) or '').strip()
        if value:
            entries.append(_entry('section', kind, value, section))
        elif kind in {'mission', 'policy'}:
            warnings.append(f"Section {section['id']} intentionally has an empty {kind} slot; publication doctrine still applies.")


def configured_context(*, publication_key=None, section_id=None, story_lineage_id=None, assignment_id=None, max_characters=0) -> dict:
    from .graphql_authoring import create_authoring_client
    load_dotenv()
    client, _ = create_authoring_client()
    return resolve_editorial_context(client, endpoint=graphql_endpoint(), publication_key=publication_key,
                                     section_id=section_id, story_lineage_id=story_lineage_id,
                                     assignment_id=assignment_id, max_characters=max_characters)


def editorial_context_command(flags: list[str]) -> None:
    parser = argparse.ArgumentParser(prog='papyrus editorial context')
    parser.add_argument('--backend', choices=['cloud'], default='cloud')
    parser.add_argument('--publication', help='Optional assertion of the hosted publication key.')
    parser.add_argument('--section')
    parser.add_argument('--story')
    parser.add_argument('--assignment')
    parser.add_argument('--max-characters', type=int, default=0)
    parser.add_argument('--format', choices=['json', 'text'], default='json')
    args = parser.parse_args(flags)
    pack = configured_context(publication_key=args.publication, section_id=args.section, story_lineage_id=args.story,
                              assignment_id=args.assignment, max_characters=args.max_characters)
    print(json.dumps(pack, indent=2, ensure_ascii=False) if args.format == 'json' else pack['text'])


EDITORIAL_WORKER_ALIASES = frozenset({'assignments.run-research', 'assignments.run-reporting', 'story-cycle.research', 'story-cycle.reporting'})

def prepare_editorial_worker_input(client, alias: str, payload: dict) -> dict:
    if alias not in EDITORIAL_WORKER_ALIASES:
        return dict(payload)
    assignment_id = payload.get('assignment_item_id')
    if not assignment_id:
        raise ValueError('Editorial worker dispatch requires a live assignment id.')
    pack = resolve_editorial_context(client, endpoint=graphql_endpoint(), assignment_id=assignment_id)
    return {**payload, 'editorial_context_text': pack['text'],
            'editorial_context_hash': pack['contextHash'],
            'editorial_context_json': json.dumps(pack, ensure_ascii=False)}
