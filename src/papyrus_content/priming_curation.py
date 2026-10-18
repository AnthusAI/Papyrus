"""Papyrus domain transformer: reuse existing reference processing without writes.

This code runs in the customer's transformer service. Papyrus owns corpus and
source artifacts; Cyclotron receives only the complete reviewed item projection.
The returned ``artifacts`` are private service working data, never GraphQL data
or the public HTTP job response. No classification label is generated here.
"""
from datetime import datetime,timezone
import json
from typing import Any

from .catalog import (catalog_item_with_external_item_id,build_prepared_reference_catalog,
    build_reference_catalog_registration_records,assert_reference_catalog_plan_safety)
from . import reference_url_text
from .relevance_sweep import reference_item

CORRECTION_FIELDS=[{'name':'title','label':'Corrected source title','required':True},
                   {'name':'abstract','label':'Corrected abstract or web summary','required':True,'multiline':True}]


class CurationNotReady(ValueError):
    """A host-authored readiness message safe to display without source errors."""


class PapyrusPrimingCuration:
    def __init__(self,*,corpus:dict[str,Any],classifier_id:str,publication_name:str,model:str|None=None,grobid_url:str|None=None,authorize_source=None):
        self.corpus=corpus;self.classifier_id=classifier_id;self.publication_name=publication_name;self.model=model;self.grobid_url=grobid_url;self.authorize_source=authorize_source

    def prepare(self,inputs:dict,previous:dict|None,feedback:str)->dict:
        if previous is not None:
            if not feedback.strip():raise ValueError('revision requires transformation feedback')
            if set(inputs)-{'title','abstract'}:raise ValueError('unknown curation correction field')
            if not str(inputs.get('title') or '').strip() or not str(inputs.get('abstract') or '').strip():
                return {**previous,'status':'clarification','message':'Provide the corrected title and abstract or web summary. This feedback does not classify the example.','fields':CORRECTION_FIELDS}
            return self._candidate(previous['reference'],str(inputs['title']),str(inputs['abstract']),previous['inputs'],previous['artifacts'],feedback,processing_path=previous.get('processing_path'))
        if set(inputs)-{'url','path'}:raise ValueError('unknown reference processing input')
        source=reference_url_text.normalize_http_url(inputs.get('url'))
        if not source:raise ValueError('source URL required')
        if inputs.get('path') not in (None,'research','web'):raise ValueError('unknown processing path override')
        if self.authorize_source:self.authorize_source(source)
        reference,registration=self._reference(source)
        options={'references':[reference],'attachments':[],'corpus_key_by_id':{reference['corpusId']:self.corpus['key']},
                 'reference_ids':{reference['id']},'force':True,'allow_discovery':True,'grobid_url':self.grobid_url}
        if self.model:options['model']=self.model
        extraction=reference_url_text.build_reference_url_text_attachment_plans(**options)
        if extraction.get('failures') or extraction.get('filterFallbacks') or not extraction.get('plans'):raise ValueError('existing reference extraction did not complete')
        for record in extraction.get('referenceRecords',[]):
            if record['expected']['id']==reference['id']:reference={**reference,**record['expected']}
        selected=next((plan for plan in extraction['plans'] if plan['record']['expected'].get('role')=='extracted_text'),None)
        if selected is None or not str(selected.get('body') or '').strip():raise ValueError('reference extraction has no complete text')
        metadata=selected['record']['expected'].get('metadata') or {}
        if isinstance(metadata,str):metadata=json.loads(metadata)
        extracted_source=metadata.get('urlExtraction') or {}
        processing_path=inputs.get('path') or ('research' if extracted_source.get('sourceKind')=='pdf' or extracted_source.get('contentType')=='application/pdf' else 'web')
        title=str(metadata.get('title') or '')
        abstract=str(metadata.get('abstract') or '')
        raw=next((plan for plan in extraction['plans'] if plan['record']['expected'].get('role')=='extracted_text_raw'),None)
        if not title and raw:
            raw_metadata=raw['record']['expected'].get('metadata') or {}
            if isinstance(raw_metadata,str):raw_metadata=json.loads(raw_metadata)
            title=str(raw_metadata.get('title') or '')
        artifacts={'registration':registration,'extraction':extraction}
        if processing_path=='web':
            from papyrus_newsroom.reference_curation_signals import reference_generate_metadata_from_extracted_text
            options={'reference_id':reference['id'],'reference':reference,'extracted_text':str(selected['body']),
                     'original_title':title or reference.get('title',''),'apply':False,'metadata_payload':{}}
            if self.model:options['model']=self.model
            generated=reference_generate_metadata_from_extracted_text(**options)
            if generated.get('status')!='generated':raise ValueError('existing metadata generation did not complete')
            title=str(generated['generated'].get('title') or '');abstract=str(generated['generated'].get('summary') or '')
            artifacts['metadata_generation']=generated
        return self._candidate(reference,title,abstract,inputs,artifacts,feedback,processing_path=processing_path)

    def _reference(self,source):
        now=datetime.now(timezone.utc).isoformat()
        catalog=build_prepared_reference_catalog({'schema_version':1,'generated_at':now,'items':[catalog_item_with_external_item_id({'url':source,'source_uri':source,'title':source})]},
            {'corpusKey':self.corpus['key'],'publicationName':self.publication_name})
        registration=build_reference_catalog_registration_records(catalog,{'corpusConfig':self.corpus,'classifierId':self.classifier_id,'status':'pending','importedAt':now})
        assert_reference_catalog_plan_safety(registration)
        reference=next(record['expected'] for record in registration['records'] if record['modelName']=='Reference')
        return reference,registration

    def _candidate(self,reference,title,abstract,inputs,artifacts,feedback,*,processing_path=None):
        processing_path=processing_path or inputs.get('path')
        working={'reference':reference,'inputs':inputs,'artifacts':artifacts,'processing_path':processing_path}
        if not title.strip() or title==reference.get('sourceUri') or not abstract.strip():
            return {**working,'status':'clarification','message':'Processing needs a complete source title and abstract or summary before preview.','fields':CORRECTION_FIELDS}
        item=reference_item(reference,source_content={'title':title,'abstract':abstract})
        return {**working,'status':'complete','candidate':{'id':item.id,'occurred_at':reference.get('sourcePublishedAt') or reference['importedAt'],
            'values':dict(item.values),'provenance':{'source_url':inputs['url'],'papyrus':{'reference_id':reference['id'],
                'external_item_id':reference.get('externalItemId'),'corpus_key':self.corpus['key'],'processing_path':processing_path,
                'transformation_feedback':feedback,'source_published_at':reference.get('sourcePublishedAt'),
                'occurrence_basis':'source publication date' if reference.get('sourcePublishedAt') else 'reference intake date',
                'preparation':artifacts.get('preparation','existing_pipeline'),
                'artifact_roles':[plan['record']['expected'].get('role') for plan in artifacts['extraction']['plans']]}}}}


class OperatorReferenceCuration(PapyrusPrimingCuration):
    """Human-supplied source fields; no claim of downloaded/extracted evidence.

    Reuses the existing intake planner, correction loop and decision projection.
    A separately configured PapyrusPrimingCuration performs automated research/web
    processing when the host has approved its source/provider services.
    """
    def prepare(self,inputs:dict,previous:dict|None,feedback:str)->dict:
        if previous is not None:return super().prepare(inputs,previous,feedback)
        if set(inputs)-{'url','path','title','abstract'}:raise ValueError('unknown operator reference field')
        source=reference_url_text.normalize_http_url(inputs.get('url'))
        if not source or inputs.get('path') not in ('research','web'):raise ValueError('source URL and research/web type required')
        reference,registration=self._reference(source)
        artifacts={'registration':registration,'extraction':{'plans':[]},'preparation':'operator_supplied'}
        return self._candidate(reference,str(inputs.get('title') or ''),str(inputs.get('abstract') or ''),inputs,artifacts,feedback)
