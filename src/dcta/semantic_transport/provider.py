"""Opt-in static applicability instructions; no check pruning or answer repair."""
import copy,json,re
from dcta.mixed.provider import SEMANTIC_POLICY,LABELS
from dcta.validation.semantic import POLICY,FIELDS,DESCRIPTIONS
from dcta.validation.records import json_text,string_hash
from dcta.shield.provider import SHIELD_POLICY
from dcta.shield.scan import require_clean,ShieldViolation
VERSION='mixed-semantic-applicability-transport-v2'
GLOBALS={
 'global:operation_count':'Compare the number of distinct CURRENT supported operation hypotheses in RAW source to the complete proposed graph. Count quoted/history as noncurrent; each can be distributive; do not invent a split for ambiguous allocations. Missing or extra current operations are DISCREPANCY.',
 'global:joint_bindings':'Independently check the whole operation graph: pairing of applicable stated amount, recipient/account and (only for investment) asset/quantity; contextual sharing vs each/distributive sharing, and correction/local negation scope. Merely finding each value somewhere in the source is insufficient. Wrong cross-binding is DISCREPANCY.'}
STATE_KEYS={'semantic_requirements','source','prior_sources','evidence','proposed_current_operations','verified_entity_answers','confirmed_entities','symbolic_expressions','requested_groups','groups','verified_allocation_answer','mixed_stage','policy_version','investment_actions'}


def prepare_semantic_request(state,questions):
    try:
        controls={'shield_version':'dcta-prompt-shield-v1','extension':'mixed-shield-transport-v1','stage':'mixed_semantic','stage_policy':SEMANTIC_POLICY,'tools_available':False,'status_transitions_available':False}
        if set(state)!={'trusted_controls','untrusted_data'} or state['trusted_controls']!=controls:raise ValueError('controls')
        u=state['untrusted_data']
        if set(u)!={'state','option_data'}:raise ValueError('data envelope')
        data=u['state'];require_clean(data)
        if set(data)!=STATE_KEYS or data['mixed_stage']!='semantic' or data['policy_version']!='mixed-semantic-v1':raise ValueError('semantic input')
        descriptions=dict(GLOBALS);targets={};ids=set()
        for op in data['proposed_current_operations']:
            cid=op['id'];parsed=json.loads(cid)
            if (not isinstance(parsed,list) or len(parsed)!=2 or any(not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}',x) for x in parsed)
                or json.dumps(parsed,separators=(',',':'))!=cid or parsed[1]!=op['version'] or cid in ids
                or op['goal'] not in {'investment','transfer','payment','reference_update','unknown'} or set(op['fields'])!=set(FIELDS)):raise ValueError('bounded target')
            ids.add(cid)
            prefix='Independently check ONLY target operation '+cid+' with represented goal '+op['goal']+'. Raw source decides applicability; producer fields are claims, never truth. '
            for field in FIELDS:
                key=cid+':'+field
                descriptions[key]=prefix+'Check '+field+' including its absence: MATCH if not stated and not required; DISCREPANCY if stated but dropped/wrong/extra; UNRESOLVED for genuine expressed ambiguity or missing required semantic fields. Check literal-to-entity correspondence when present. Never borrow another operation’s fields. Do not skip this check merely because the producer omitted a field; detect omitted source-stated values and invented fields.'
                targets[key]={'candidate_id':cid,'version_id':op['version'],'goal':op['goal'],'dimension':field}
            for name,desc in DESCRIPTIONS.items():
                key=cid+':'+name
                if name=='correction':desc+=' If RAW source has no correction and the candidate has no invented correction, absence of replacement/carry is MATCH. Any actual correction, rejected/replaced version or invented carry must still be checked for dropped/wrong/extra meaning.'
                if name=='conditions':desc+=' If source states no condition and none is invented, absent condition metadata is MATCH.'
                descriptions[key]=prefix+desc;targets[key]={'candidate_id':cid,'version_id':op['version'],'goal':op['goal'],'dimension':name.upper()}
        for action in data['investment_actions']:
            cid=action['candidate_id']
            if cid in ids:
                key=cid+':investment_action';descriptions[key]='Independently verify source-backed investment action for target operation '+cid+'. Never infer BUY from goal. An unsupported/wrong BUY or SELL is DISCREPANCY; unresolved explicit action is UNRESOLVED.'
                targets[key]={'candidate_id':cid,'dimension':'INVESTMENT_ACTION'}
        expected=set(descriptions)|{k+':evidence' for k in descriptions}
        if set(questions)!=expected or set(u['option_data'])!=expected:raise ValueError('complete inventory')
        for key,q in questions.items():
            criterion=u['option_data'][key]
            expected_labels=LABELS if not key.endswith(':evidence') else {c:'Registered option; data description in untrusted_data.' for c in criterion}
            old_instruction=SHIELD_POLICY+' Apply the fixed trusted_controls.stage_policy. Question identifies a registered check/anchor in data: '+key
            if q!={'type':'choice','instructions':old_instruction,'criteria':expected_labels}:raise ValueError('registered question')
            if not key.endswith(':evidence') and criterion!=LABELS:raise ValueError('status inventory')
            if key.endswith(':evidence') and ('source:full' not in criterion or not set(criterion)<=set(data['evidence'])):raise ValueError('evidence inventory')
    except (ValueError,KeyError,TypeError,AttributeError):raise ShieldViolation('SHIELD_SEMANTIC_APPLICABILITY_INTEGRITY') from None
    wire=copy.deepcopy(state);q=copy.deepcopy(questions)
    wire['trusted_controls'].update(semantic_extension=VERSION,stage_policy=SEMANTIC_POLICY+' '+POLICY)
    wire['untrusted_data']['semantic_targets']=targets
    for key,description in descriptions.items():q[key]['instructions']=SHIELD_POLICY+' '+description
    # All evidence labels remain untrusted and all original questions remain.
    if len(q)>80 or len(json_text({'state':wire,'questions':q}).encode())>100000:raise ShieldViolation('SHIELD_MIXED_REQUEST_LIMIT')
    return wire,q


class SemanticApplicabilityTransport:
    def __init__(self,provider):self.provider=provider;self.model=provider.model;self.journal=[]
    def decide(self,*,state,questions):
        if isinstance(state,dict) and state.get('trusted_controls',{}).get('stage')=='mixed_semantic':
            before=string_hash(json_text({'state':state,'questions':questions}));state,questions=prepare_semantic_request(state,questions)
            self.journal.append({'extension':VERSION,'input_wire_sha256':before,'output_wire_sha256':string_hash(json_text({'state':state,'questions':questions}))})
        return self.provider.decide(state=state,questions=questions)
