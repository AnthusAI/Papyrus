"""Synthetic Papyrus curation fixtures; no source fetches, providers, or cloud writes."""
import pytest
from papyrus_content.priming_curation import PapyrusPrimingCuration


def pipeline_fixture(monkeypatch):
    from papyrus_content import reference_url_text
    calls=[]
    def plan(**kwargs):
        calls.append(kwargs)
        reference=kwargs['references'][0]
        return {'failures':[], 'plans':[{'reference':reference,'record':{'modelName':'ReferenceAttachment','expected':{'id':'attachment','role':'extracted_text','metadata':{'abstract':'Synthetic research abstract','title':'Synthetic extracted title','extractorId':'fixture'}}},'body':'Synthetic extracted full body'}], 'referenceRecords':[], 'graphRecords':[], 'filterFallbacks':[]}
    monkeypatch.setattr(reference_url_text,'build_reference_url_text_attachment_plans',plan)
    return calls


def service():return PapyrusPrimingCuration(corpus={'key':'synthetic-corpus','name':'Synthetic','path':'synthetic'},classifier_id='scope',publication_name='Synthetic publication')


def test_research_path_reuses_registration_and_extraction_planners_without_apply(monkeypatch):
    calls=pipeline_fixture(monkeypatch)
    result=service().prepare({'url':'https://example.invalid/paper','path':'research'},None,'')
    item=result['candidate']
    assert item['values']['title']=='Synthetic extracted title'
    assert item['values']['abstract']=='Synthetic research abstract'
    assert 'Synthetic research abstract' in item['values']['text']
    assert calls[0]['allow_discovery'] is True and calls[0]['force'] is True
    assert result['artifacts']['registration']['records']
    assert result['artifacts']['extraction']['plans'][0]['body']=='Synthetic extracted full body'
    assert 'Synthetic extracted full body' not in str(item)
    assert item['provenance']['papyrus']['processing_path']=='research'
    assert all('apply' not in call for call in calls)


def test_web_path_reuses_existing_metadata_generation_with_apply_false(monkeypatch):
    pipeline_fixture(monkeypatch)
    from papyrus_newsroom import reference_curation_signals
    calls=[]
    def generate(**kwargs):
        calls.append(kwargs)
        return {'status':'generated','generated':{'title':'Synthetic web title','summary':'Synthetic budgeted summary'},'records':[]}
    monkeypatch.setattr(reference_curation_signals,'reference_generate_metadata_from_extracted_text',generate)
    result=service().prepare({'url':'https://example.invalid/post','path':'web'},None,'')
    assert result['candidate']['values']['abstract']=='Synthetic budgeted summary'
    assert calls[0]['apply'] is False and calls[0]['extracted_text']=='Synthetic extracted full body'
    assert result['candidate']['provenance']['papyrus']['processing_path']=='web'


def test_url_alone_infers_paper_from_existing_extraction_without_manual_fields(monkeypatch):
    calls=pipeline_fixture(monkeypatch)
    original=__import__('papyrus_content.reference_url_text',fromlist=['build_reference_url_text_attachment_plans']).build_reference_url_text_attachment_plans
    def paper(**kwargs):
        result=original(**kwargs)
        result['plans'][0]['record']['expected']['metadata'].update(urlExtraction={'sourceKind':'pdf','contentType':'application/pdf'},sourcePlugin='arxiv')
        return result
    monkeypatch.setattr('papyrus_content.reference_url_text.build_reference_url_text_attachment_plans',paper)
    inputs={'url':'https://arxiv.org/abs/2503.15739'}
    result=service().prepare(inputs,None,'')
    assert result['status']=='complete'
    assert result['inputs']==inputs
    assert result['candidate']['provenance']['papyrus']['processing_path']=='research'
    assert calls[0]['allow_discovery'] is True
    assert 'labels' not in result['candidate']
    corrected=service().prepare({'title':'Corrected title','abstract':'Corrected abstract'},result,'Correct extracted text')
    assert corrected['inputs']==inputs
    assert corrected['candidate']['provenance']['papyrus']['processing_path']=='research'


def test_url_alone_infers_web_and_runs_existing_summary_generation(monkeypatch):
    pipeline_fixture(monkeypatch)
    from papyrus_newsroom import reference_curation_signals
    calls=[]
    def generate(**kwargs):
        calls.append(kwargs)
        return {'status':'generated','generated':{'title':'Extracted web title','summary':'Generated web summary'},'records':[]}
    monkeypatch.setattr(reference_curation_signals,'reference_generate_metadata_from_extracted_text',generate)
    result=service().prepare({'url':'https://example.invalid/post'},None,'')
    assert result['candidate']['values']['abstract']=='Generated web summary'
    assert result['candidate']['provenance']['papyrus']['processing_path']=='web'
    assert len(calls)==1 and calls[0]['apply'] is False


def test_arxiv_abstract_url_uses_existing_paper_resolver():
    from papyrus_content.source_site_plugins import resolve_source_site_enrichment
    fetched=[]
    def fetch(url):
        fetched.append(url)
        return '<meta name="citation_abstract" content="Paper&#39;s fixture abstract">'
    result=resolve_source_site_enrichment(reference={},source_uri='https://arxiv.org/abs/2503.15739',fetcher=fetch)
    assert fetched==['https://arxiv.org/abs/2503.15739']
    assert result['pluginKey']=='arxiv'
    assert result['canonicalSourceUri']=='https://arxiv.org/pdf/2503.15739.pdf'
    assert result['metadata']['abstract']=="Paper's fixture abstract"


def test_arxiv_uses_paper_abstract_instead_of_generic_page_description():
    from papyrus_content.source_site_plugins import resolve_source_site_enrichment
    html='''<meta name="description" content="Abstract page for arXiv paper 2503.15739">
    <blockquote class="abstract mathjax"><span class="descriptor">Abstract:</span>
    Actual <em>paper</em> abstract &amp; evidence.</blockquote>'''
    result=resolve_source_site_enrichment(reference={},source_uri='https://arxiv.org/abs/2503.15739',fetcher=lambda url:html)
    assert result['metadata']['abstract']=='Actual paper abstract & evidence.'


def test_arxiv_generic_page_description_is_not_a_complete_abstract():
    from papyrus_content.source_site_plugins import resolve_source_site_enrichment
    result=resolve_source_site_enrichment(reference={},source_uri='https://arxiv.org/abs/2503.15739',fetcher=lambda url:'<meta name="description" content="Abstract page for arXiv paper 2503.15739">')
    assert result['metadata']['abstract']==''


def test_missing_abstract_requests_clarification_and_human_revision_preserves_feedback(monkeypatch):
    pipeline_fixture(monkeypatch)
    processor=service();result=processor.prepare({'url':'https://example.invalid/paper','path':'research'},None,'')
    revised=processor.prepare({'title':'Human corrected title','abstract':'Human corrected abstract'},result,'Correct the extraction')
    assert revised['candidate']['values']['abstract']=='Human corrected abstract'
    assert revised['candidate']['provenance']['papyrus']['transformation_feedback']=='Correct the extraction'
    assert 'labels' not in revised['candidate']
    result['candidate']['values'].pop('abstract')
    clarification=processor.prepare({},result,'Abstract was omitted')
    assert clarification['status']=='clarification'
    assert {f['name'] for f in clarification['fields']}>={'title','abstract'}


def test_failure_or_unknown_path_never_returns_a_url_only_item(monkeypatch):
    from papyrus_content import reference_url_text
    monkeypatch.setattr(reference_url_text,'build_reference_url_text_attachment_plans',lambda **_:{'failures':[{'error':'Synthetic failure'}],'plans':[]})
    with pytest.raises(ValueError):service().prepare({'url':'https://example.invalid/paper','path':'research'},None,'')
    with pytest.raises(ValueError):service().prepare({'url':'https://example.invalid/paper','path':'invented'},None,'')


def test_operator_supplied_reference_fields_use_existing_projection_without_network_or_labels(monkeypatch):
    from papyrus_content.priming_curation import OperatorReferenceCuration
    from papyrus_content import reference_url_text
    monkeypatch.setattr(reference_url_text,'build_reference_url_text_attachment_plans',lambda **kwargs:(_ for _ in ()).throw(AssertionError('operator fields must not fetch/extract')))
    processor=OperatorReferenceCuration(corpus={'key':'local-review','name':'Local review','path':'local-review'},classifier_id='editorial',publication_name='Threat Intelligence')
    for path in ('research','web'):
        result=processor.prepare({'url':f'https://example.invalid/{path}','path':path,'title':'Operator-provided source title','abstract':'Operator-provided abstract or summary.'},None,'')
        assert result['status']=='complete' and result['candidate']['values']['abstract']=='Operator-provided abstract or summary.'
        assert result['candidate']['provenance']['papyrus']['preparation']=='operator_supplied'
        assert result['candidate']['provenance']['papyrus']['processing_path']==path
        assert result['artifacts']['registration']['records'] and result['artifacts']['extraction']['plans']==[]
        assert 'labels' not in result['candidate']
        revised=processor.prepare({'title':'Corrected title','abstract':'Corrected summary.'},result,'Correct the supplied fields.')
        assert revised['candidate']['values']['abstract']=='Corrected summary.'
        assert revised['candidate']['provenance']['papyrus']['preparation']=='operator_supplied'


def test_operator_fields_request_missing_content_and_never_make_up_labels():
    from papyrus_content.priming_curation import OperatorReferenceCuration
    processor=OperatorReferenceCuration(corpus={'key':'local','name':'Local','path':'local'},classifier_id='editorial',publication_name='Configured publication')
    result=processor.prepare({'url':'https://example.invalid/paper','path':'research','title':'','abstract':''},None,'')
    assert result['status']=='clarification' and 'candidate' not in result
    with pytest.raises(ValueError):processor.prepare({'url':'https://example.invalid/paper','path':'research','title':'Title','abstract':'Text','label':'publish'},None,'')


def test_reported_filter_fallback_stops_priming_before_metadata(monkeypatch):
    pipeline_fixture(monkeypatch)
    from papyrus_content import reference_url_text
    from papyrus_newsroom import reference_curation_signals
    original=reference_url_text.build_reference_url_text_attachment_plans
    def failed_filter(**kwargs):
        result=original(**kwargs)
        result['filterFallbacks']=[{'reason':{'code':'invalid_provider_output'}}]
        return result
    monkeypatch.setattr(reference_url_text,'build_reference_url_text_attachment_plans',failed_filter)
    monkeypatch.setattr(reference_curation_signals,'reference_generate_metadata_from_extracted_text',lambda **kwargs:pytest.fail('Failed article filtering must not trigger metadata'))
    with pytest.raises(ValueError,match='extraction did not complete'):
        service().prepare({'url':'https://example.invalid/source'},None,'')
