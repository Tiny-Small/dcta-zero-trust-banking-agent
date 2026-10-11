"""Explicit action criteria/targets beneath the accepted mixed shield.

No deterministic action derivation or answer rewriting: the model still
selects a registered action; frame/discourse selection remains independent.
"""
import copy,json,re
from dcta.ponder.input import PonderInputSnapshot
from dcta.mixed.policy import build_registry,build_request,RELATION_POLICY
from dcta.shield.provider import SHIELD_POLICY
from dcta.shield.scan import require_clean,ShieldViolation
from dcta.validation.records import json_text,string_hash
VERSION='investment-action-shield-transport-v2'
DEFINITIONS={
 'BUY':'The linked predicate explicitly states buying/acquiring the investment asset. Choose BUY when that explicit acquisition action is established; not merely because the goal is investment.',
 'SELL':'The linked predicate explicitly states selling/disposing of the investment asset. Choose SELL when that explicit disposal action is established; never convert acquisition into sale.',
 'UNSPECIFIED':'The linked predicate does not establish buying or selling, or action remains unresolved. Not a generic safe/default answer when explicit supported BUY/SELL evidence is present.'}


def prepare_action_request(state,questions):
    try:
        expected_controls={'shield_version':'dcta-prompt-shield-v1','extension':'mixed-shield-transport-v1','stage':'mixed_relation','stage_policy':RELATION_POLICY,'tools_available':False,'status_transitions_available':False}
        if set(state)!={'trusted_controls','untrusted_data'} or state['trusted_controls']!=expected_controls:raise ValueError('controls')
        data=state['untrusted_data']['state'];require_clean(data)
        snapshot=PonderInputSnapshot.model_validate_json(json.dumps(data['snapshot']))
        registry=build_registry(snapshot);expected,logical=build_request(snapshot,registry)
        if data!=expected or state['untrusted_data']!={'state':expected,'option_data':{k:v['criteria'] for k,v in logical.items()}}:raise ValueError('registry replay')
        expected_q={k:{'type':'choice','instructions':SHIELD_POLICY+' Apply the fixed trusted_controls.stage_policy. Question identifies a registered check/anchor in data: '+k,'criteria':{c:'Registered option; data description in untrusted_data.' for c in v['criteria']}} for k,v in logical.items()}
        if questions!=expected_q:raise ValueError('shield question replay')
        anchors={a.id:a for a in snapshot.relational_anchors};frames=[f for p in registry.packets for f in p.frames]
        targets={}
        for key in questions:
            if not key.startswith('action:'):continue
            aid=key[len('action:'):]
            if not re.fullmatch(r'a:PREDICATE:[0-9]+:[0-9]+',aid):raise ValueError('bounded predicate ID')
            linked=[f for f in frames if f.anchor_id==aid]
            if len(linked)!=1 or linked[0].frame_id!='mixed:'+aid:raise ValueError('frame/anchor association')
            a=anchors[aid]
            if (a.kind!='PREDICATE' or a.evidence.source_id!=snapshot.current_source.id
                or not 0<=a.evidence.start<a.evidence.end<=len(snapshot.current_source.text)
                or aid!=f'a:PREDICATE:{a.evidence.start}:{a.evidence.end}'
                or snapshot.current_source.text[a.evidence.start:a.evidence.end]!=a.evidence.text):raise ValueError('source evidence')
            if not set(questions[key]['criteria'])<=set(DEFINITIONS):raise ValueError('action inventory')
            targets[key]={'frame_id':linked[0].frame_id,'anchor':a.model_dump(mode='json')}
    except (ValueError,TypeError,KeyError,AttributeError):raise ShieldViolation('SHIELD_ACTION_TARGET_INTEGRITY') from None
    wire=copy.deepcopy(state);q=copy.deepcopy(questions)
    wire['trusted_controls']['action_extension']=VERSION;wire['untrusted_data']['action_targets']=targets
    for key,target in targets.items():
        q[key]['instructions']=(SHIELD_POLICY+' Classify only the action of target investment frame hypothesis '+target['frame_id']+' supported by predicate anchor '+target['anchor']['id']+'. '
            'Its exact source-linked predicate evidence is in untrusted_data.action_targets for this question. '
            'Use the static action criteria and this linked predicate evidence; generic investment alone never implies BUY. '
            'Frame selection and current/historical/hypothetical/quoted status are separate registered decisions. An action answer cannot create or make a frame current.')
        q[key]['criteria']={c:DEFINITIONS[c] for c in q[key]['criteria']}
    if len(q)>80 or len(json_text({'state':wire,'questions':q}).encode())>100000:raise ShieldViolation('SHIELD_MIXED_REQUEST_LIMIT')
    return wire,q

class ActionTargetTransport:
    """Opt-in transport decorator; never changes a returned answer."""
    def __init__(self,provider):self.provider=provider;self.model=provider.model;self.journal=[]
    def decide(self,*,state,questions):
        if isinstance(state,dict) and state.get('trusted_controls',{}).get('stage')=='mixed_relation':
            before=string_hash(json_text({'state':state,'questions':questions}));state,questions=prepare_action_request(state,questions)
            self.journal.append({'extension':VERSION,'input_wire_sha256':before,'output_wire_sha256':string_hash(json_text({'state':state,'questions':questions}))})
        return self.provider.decide(state=state,questions=questions)
