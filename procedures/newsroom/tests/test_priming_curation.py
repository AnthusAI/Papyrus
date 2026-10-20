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


@pytest.mark.parametrize('published', [None, '2021-01-07T00:00:00Z'])
def test_completed_preview_drops_stale_intake_reason_and_distinguishes_source_date(monkeypatch, published):
    """Saved CISA run regression: generated summary must not claim unavailable."""
    pipeline_fixture(monkeypatch)
    processor=service()
    reference,registration=processor._reference('https://example.invalid/2021/01/07/incident')
    stale=reference['curationStatusReason']
    assert 'Summary is not yet available' in stale
    if published:reference['sourcePublishedAt']=published
    monkeypatch.setattr(processor,'_reference',lambda _: (reference,registration))
    result=processor.prepare({'url':reference['sourceUri'],'path':'research'},None,'')
    item=result['candidate']
    assert 'Summary is not yet available' not in item['values']['text']
    assert 'ingestion_rationale' not in item['values']
    assert reference['curationStatusReason']==stale  # raw intake provenance unchanged
    assert 'Synthetic research abstract' in item['values']['text']
    if published:
        assert 'Published: 2021-01-07' in item['values']['text']
        assert item['occurred_at']==published
    else:
        assert 'Source publication date: unknown' in item['values']['text']
        assert 'Reference intake date:' in item['values']['text']
        assert item['occurred_at']==reference['importedAt']
        assert '2021-01-07' not in item['values']['text']  # URL is not date evidence
    revised=processor.prepare({'title':'Corrected title','abstract':'Corrected summary'},result,'Remove extraction noise')
    assert 'Summary is not yet available' not in revised['candidate']['values']['text']
    assert revised['candidate']['provenance']['papyrus']['transformation_feedback']=='Remove extraction noise'


def test_operational_projection_keeps_existing_intake_reason():
    from papyrus_content.relevance_sweep import reference_item
    reference,_=service()._reference('https://example.invalid/paper')
    item=reference_item(reference)
    assert item.values['ingestion_rationale']==reference['curationStatusReason']


def failing_pipeline(monkeypatch,**result):
    from papyrus_content import reference_url_text
    base={'failures':[],'plans':[],'referenceRecords':[],'graphRecords':[],'filterFallbacks':[]}
    monkeypatch.setattr(reference_url_text,'build_reference_url_text_attachment_plans',lambda **kwargs:{**base,**result})


def test_extraction_failure_names_its_reason_code_and_message(monkeypatch):
    from papyrus_content.priming_curation import ExtractionIncomplete
    failing_pipeline(monkeypatch,failures=[{'reason':{'code':'grobid_unreachable','message':'GROBID did not answer.'}}])
    with pytest.raises(ExtractionIncomplete) as raised:
        service().prepare({'url':'https://example.invalid/paper'},None,'')
    assert 'grobid_unreachable' in str(raised.value) and 'GROBID did not answer.' in str(raised.value)
    assert raised.value.code=='grobid_unreachable' and raised.value.transient is True


def test_bad_source_failure_is_not_transient(monkeypatch):
    from papyrus_content.priming_curation import ExtractionIncomplete
    failing_pipeline(monkeypatch,failures=[{'reason':{'code':'empty_text','message':'No text.'}}])
    with pytest.raises(ExtractionIncomplete) as raised:
        service().prepare({'url':'https://example.invalid/paper'},None,'')
    assert raised.value.code=='empty_text' and raised.value.transient is False


def test_filter_fallback_names_its_own_cause(monkeypatch):
    failing_pipeline(monkeypatch,filterFallbacks=[{'reason':{'code':'article_filter_failed','message':'Filter broke.'}}])
    with pytest.raises(ValueError,match='article_filter_fallback.*article_filter_failed.*Filter broke'):
        service().prepare({'url':'https://example.invalid/paper'},None,'')


def test_empty_plan_set_names_its_own_cause(monkeypatch):
    failing_pipeline(monkeypatch)
    with pytest.raises(ValueError,match='no_extraction_plans'):
        service().prepare({'url':'https://example.invalid/paper'},None,'')


# Recorded fixtures: GROBID boilerplate titles and the landing pages that correct them.
ARXIV_ABS_ATTENTION='<html><head><title>[1706.03762] Attention Is All You Need</title><meta name="citation_title" content="Attention Is All You Need"></head></html>'
ARXIV_ABS_GPT4='<html><head><title>[2303.08774] GPT-4 Technical Report - arXiv</title><meta property="og:title" content="[2303.08774] GPT-4 Technical Report"></head></html>'
ARXIV_API_GPT4='<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>GPT-4 Technical\n  Report</title></entry></feed>'


def grobid_title_pipeline(monkeypatch,title,landing):
    from papyrus_content import priming_curation
    pipeline_fixture(monkeypatch)
    from papyrus_content import reference_url_text
    original=reference_url_text.build_reference_url_text_attachment_plans
    def plan(**kwargs):
        result=original(**kwargs)
        result['plans'][0]['record']['expected']['metadata']['title']=title
        return result
    monkeypatch.setattr(reference_url_text,'build_reference_url_text_attachment_plans',plan)
    fetched=[]
    def fetch(url):
        fetched.append(url)
        if url not in landing:raise OSError('no recorded fixture')
        return landing[url]
    monkeypatch.setattr(priming_curation,'_fetch_landing_text',fetch)
    return fetched


def test_grobid_licence_boilerplate_loses_to_arxiv_citation_title(monkeypatch):
    fetched=grobid_title_pipeline(monkeypatch,'Provided proper attribution is provided, Google hereby grants permission… Attention Is All You Need',{'https://arxiv.org/abs/1706.03762':ARXIV_ABS_ATTENTION})
    result=service().prepare({'url':'https://arxiv.org/abs/1706.03762'},None,'')
    assert result['candidate']['values']['title']=='Attention Is All You Need'
    assert fetched==['https://arxiv.org/abs/1706.03762']


def test_grobid_author_list_loses_to_cleaned_arxiv_og_title_for_pdf_url(monkeypatch):
    fetched=grobid_title_pipeline(monkeypatch,'Core contributors 11 Gabriel Goh Long context co-lead…',{'https://arxiv.org/abs/2303.08774':ARXIV_ABS_GPT4})
    result=service().prepare({'url':'https://arxiv.org/pdf/2303.08774'},None,'')
    assert result['candidate']['values']['title']=='GPT-4 Technical Report'
    assert fetched==['https://arxiv.org/abs/2303.08774']


def test_arxiv_export_api_title_is_used_when_abs_page_has_no_title(monkeypatch):
    grobid_title_pipeline(monkeypatch,'Core contributors 11 Gabriel Goh Long context co-lead…',{'https://arxiv.org/abs/2303.08774':'<html></html>','http://export.arxiv.org/api/query?id_list=2303.08774':ARXIV_API_GPT4})
    result=service().prepare({'url':'https://arxiv.org/pdf/2303.08774.pdf'},None,'')
    assert result['candidate']['values']['title']=='GPT-4 Technical Report'


def test_good_grobid_title_is_kept_when_no_landing_metadata_exists(monkeypatch):
    grobid_title_pipeline(monkeypatch,'A Perfectly Good Paper Title',{})
    result=service().prepare({'url':'https://example.invalid/paper','path':'research'},None,'')
    assert result['candidate']['values']['title']=='A Perfectly Good Paper Title'


def test_bad_grobid_title_without_landing_metadata_asks_for_correction(monkeypatch):
    grobid_title_pipeline(monkeypatch,'Core contributors 11 Gabriel Goh Long context co-lead…',{})
    result=service().prepare({'url':'https://example.invalid/paper','path':'research'},None,'')
    assert result['status']=='clarification'


def test_title_sanity_guard():
    from papyrus_content.priming_curation import plausible_title
    assert plausible_title('Attention Is All You Need')
    assert not plausible_title('x'*201)
    assert not plausible_title('Anna Lee, Bo Chen, Cy Diaz, Di Eng, Ed Fox')
    assert not plausible_title('Permission is granted to reproduce')
