"""Seed YAML is a one-time import into the database; it never overwrites what editors saved."""
from papyrus_content.newsroom_commands import import_missing_records
from papyrus_content.newsroom_doctrine import build_publication_doctrine_records
from papyrus_content.newsroom_sections import build_newsroom_section_records


class Database:
    def __init__(self):
        self.sections, self.items, self.writes = {}, {}, []

    def get_record(self, model, record_id):
        return self.sections.get(record_id) if model == 'NewsroomSection' else None

    def list_by_index(self, index, slug):
        assert index == 'itemBySlug'
        return list(self.items.get(slug, []))

    def create_record(self, model, payload):
        self.writes.append((model, payload['id']))
        if model == 'NewsroomSection':
            self.sections[payload['id']] = payload
        else:
            self.items.setdefault(payload['slug'], []).append(payload)


SECTION = {'id': 'news', 'title': 'News', 'shortTitle': 'News', 'type': 'canonical', 'editorialMission': 'Seed mission',
           'editorialPolicy': 'Seed policy', 'enabled': True, 'sortOrder': 1, 'defaultArticleTypes': [],
           'defaultPageBudget': None, 'assignmentGuidance': None, 'killCriteria': None, 'visualGuidance': None}
DOCTRINE = [{'kind': 'mission', 'body': ['Seed mission']}, {'kind': 'policy', 'body': ['Seed policy']}]


def test_first_import_creates_and_rerun_changes_nothing():
    database = Database()
    records = build_newsroom_section_records([SECTION]) + build_publication_doctrine_records(DOCTRINE)
    assert [c['action'] for c in import_missing_records(database, records)] == ['create'] * 3
    assert [c['action'] for c in import_missing_records(database, records)] == ['noop'] * 3
    assert len(database.writes) == 3


def test_newer_database_edits_are_never_overwritten():
    database = Database()
    database.sections['news'] = {'id': 'news', 'editorialPolicy': 'Edited in the newsroom'}
    edited = {'id': 'item-editorial-doctrine-policy-v2', 'slug': 'editorial-doctrine-policy', 'body': ['Edited policy']}
    database.items['editorial-doctrine-policy'] = [edited]
    records = build_newsroom_section_records([SECTION]) + build_publication_doctrine_records(DOCTRINE)
    actions = {c['expected']['id']: c['action'] for c in import_missing_records(database, records)}
    assert actions['news'] == 'noop' and actions['item-editorial-doctrine-policy-v1'] == 'noop'
    assert actions['item-editorial-doctrine-mission-v1'] == 'create'
    assert database.sections['news']['editorialPolicy'] == 'Edited in the newsroom'
    assert database.items['editorial-doctrine-policy'] == [edited]
