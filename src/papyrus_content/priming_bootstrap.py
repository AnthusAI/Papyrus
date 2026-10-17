"""Explicit accepted-catalog snapshot for a NEW Papyrus relevance Cyclotron.

No source fetching, extraction, labels, provider clients or storage adapters live
here. The shared PrimingPanel/PrimingService owns human acceptance. A snapshot is
an operator-selected input, never a prerequisite or an automatic catalog refresh.
"""
from dataclasses import asdict,dataclass
import hashlib
import json


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def definition_scope(definition):
    return [{'id':spec.id,'question':spec.question,'labels':list(spec.labels),'input_field':spec.input_field}
            for spec in definition.classifiers]


@dataclass(frozen=True)
class AcceptedPrimingSnapshot:
    """Immutable captured accepted values, human judgments and classifier pins."""
    payload: str
    fingerprint: str

    @classmethod
    def capture(cls,service,*,list_id,classifiers,definition):
        contract=service.contract(list_id,classifiers)
        expected=definition_scope(definition)
        actual=[{'id':row['id'],'question':row['config']['question'],
                 'labels':[label['label'] for label in row['config']['classes']],
                 'input_field':row['config'].get('input_field','text')} for row in contract['classifiers']]
        if sorted(actual,key=lambda row:row['id'])!=sorted(expected,key=lambda row:row['id']):
            raise ValueError('priming classifiers must match the relevance definition and question')
        examples=service.examples(list_id,classifiers)
        # Preserve explicit selection provenance in the SDK's existing context data.
        pins=[{'id':row['id'],'revision':row['revision']} for row in contract['classifiers']]
        encoded={cid:[{**asdict(row),'context':{**row.context,'priming_origin':canonical({'list_id':list_id,'classifiers':pins})}}
                      for row in rows] for cid,rows in examples.items()}
        if not all(encoded.get(row['id']) for row in expected):raise ValueError('every selected classifier needs accepted priming examples')
        payload=canonical({'version':'papyrus-accepted-priming/v1','list_id':list_id,'classifiers':pins,
                           'definition':expected,'examples':encoded})
        snapshot=cls(payload,hashlib.sha256(payload.encode()).hexdigest())
        snapshot.for_definition(definition)
        return snapshot

    def for_definition(self,definition):
        from decision_flywheel.priming_context import decode_priming,encode_priming
        if hashlib.sha256(self.payload.encode()).hexdigest()!=self.fingerprint:raise ValueError('priming snapshot fingerprint changed')
        data=json.loads(self.payload)
        if data.get('version')!='papyrus-accepted-priming/v1' or data.get('definition')!=definition_scope(definition):
            raise ValueError('priming snapshot definition changed; explicitly select examples again')
        examples=decode_priming(data['examples'])
        # Reuse native label, rationale, task and size validation before host side effects.
        encode_priming(examples,{spec.id:spec.task for spec in definition.classifiers})
        return examples
