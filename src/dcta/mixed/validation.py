"""Versioned independent mixed graph observer; original validator remains frozen."""
import json
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.serialization import content_sha256
from dcta.ponder_mvp.consumer import consume
from dcta.validation.input import ValidationInput,build_input as core_input
from dcta.validation.checks import deterministic_findings,finding
from dcta.validation.semantic import build_request as core_request
from dcta.validation.records import (Result,Finding,SemanticCheck,ValidationTarget,ValidatorObservation,json_text,string_hash)
from dcta.ponder_mvp._extractor.providers.decisions import parse_choices
from .records import MixedInterpretation
from .policy import verify_interpretation
from .provider import LABELS

VERSION='mixed-semantic-v1'
class MixedSemanticInput(FrozenRecord):
    schema_version: Literal['mixed-semantic-input-v1']='mixed-semantic-input-v1'
    interpretation: MixedInterpretation
    core: ValidationInput

class MixedSemanticDecision(FrozenRecord):
    schema_version: Literal['mixed-semantic-decision-v1']='mixed-semantic-decision-v1'
    result: Result
    validation_input_sha256: str
    observation: ValidatorObservation
    checks: tuple[SemanticCheck,...]
    findings: tuple[Finding,...]

class MixedSemanticGate(FrozenRecord):
    schema_version: Literal['mixed-semantic-gate-v1']='mixed-semantic-gate-v1'
    state: Literal['FROZEN','ELIGIBLE_FOR_BUSINESS_CHECKS']
    result: Result
    input_sha256: str
    decision_sha256: str


def build_input(interpretation,grounding,parents=(),directory=None):
    i=verify_interpretation(interpretation)
    return MixedSemanticInput(interpretation=i,core=core_input(consume(i.compilation),grounding,grounding_parents=parents,directory=directory))


def _findings(data):
    core=data.core
    try:
        i=verify_interpretation(data.interpretation)
        if core_input(consume(i.compilation),core.grounding,grounding_parents=core.grounding_parents,directory=core.directory)!=core:raise ValueError('mixed validation transport replay')
    except ValueError:return (finding(core,'CONTRACT_ERROR','MIXED_INPUT_INTEGRITY','INPUT','Mixed interpretation/input differs from replay'),)
    # This is the sole new representational capability; original evaluator still
    # reports the original limitation. No other finding is dropped or repaired.
    out=[f for f in deterministic_findings(core) if f.kind!='INVESTMENT_ACTION_UNREPRESENTED']
    current={x.candidate.id:x for x in core.context}
    for action in i.actions:
        if action.candidate_id in current and action.action=='UNSPECIFIED':out.append(finding(core,'UNRESOLVED','ACTION_UNSPECIFIED','INVESTMENT_ACTION','No explicit BUY/SELL action decision',item=current[action.candidate_id],evidence_ids=('anchor:'+action.anchor_id,)))
    return tuple(out)


def build_request(data):
    data=MixedSemanticInput.model_validate(data);state,q,spec=core_request(data.core)
    state.pop('validator_policy')
    state.update(mixed_stage='semantic',policy_version=VERSION,investment_actions=[a.model_dump(mode='json') for a in data.interpretation.actions])
    for a in data.interpretation.actions:
        item=next((x for x in data.core.targets if x.candidate.id==a.candidate_id),None)
        if item is None:continue
        key=a.candidate_id+':investment_action'
        q[key]={'type':'choice','instructions':'Independently verify source-backed investment action. Never infer BUY from goal.','criteria':LABELS}
        q[key+':evidence']={'type':'choice','instructions':'Cite original predicate/source evidence.','criteria':{'source:full':data.core.snapshot.current_source.text,'anchor:'+a.anchor_id:a.evidence.text}}
        spec[key]=('INVESTMENT_ACTION',item)
    if len(q)>80 or len(json_text({'state':state,'questions':q}).encode())>28000:raise OverflowError('LIMIT_EXCEEDED mixed validator')
    return state,q,spec


def observation(data,request,response,model=None):
    rq=json_text(request);rs=json_text(response)
    return ValidatorObservation(mode='MODEL' if model else 'DETERMINISTIC',validator_version=VERSION,validation_input_sha256=content_sha256(data),configured_model=model,request_json=rq,request_sha256=string_hash(rq),response_json=rs,response_sha256=string_hash(rs))


def finalize(data,obs):
    data=MixedSemanticInput.model_validate(data);obs=ValidatorObservation.model_validate(obs);out=list(_findings(data));checks=[]
    if obs.validator_version!=VERSION or obs.validation_input_sha256!=content_sha256(data) or string_hash(obs.request_json)!=obs.request_sha256 or string_hash(obs.response_json)!=obs.response_sha256:out.append(finding(data.core,'CONTRACT_ERROR','MIXED_OBSERVATION_INTEGRITY','INPUT','Independent observation version/hash mismatch'))
    elif obs.mode=='MODEL':
        try:
            state,q,spec=build_request(data)
            if json.loads(obs.request_json)!={'state':state,'questions':q}:raise ValueError('mixed request replay')
            response=json.loads(obs.response_json);env=response.get('raw_response')
            if response.get('http_status')!=200 or response.get('error_class') or not isinstance(env,dict):raise ValueError('observer transport')
            if set(env)-{'id','created','object','model','provider','answers','usage'}:raise ValueError('extra observer output')
            resolved=env.get('model');model=obs.configured_model
            if env.get('provider')!='TypeSafe' or not model or not isinstance(resolved,str) or not (resolved==model or resolved.startswith(model+'-')):raise ValueError('observer identity')
            aa=env.get('answers')
            if not isinstance(aa,dict) or any(not isinstance(a,dict) or set(a)-{'type','choice','confidence','probabilities'} for a in aa.values()):raise ValueError('observer answer shape')
            answers,errors=parse_choices(env,q)
            if errors:raise ValueError('unregistered observer choice')
            for key,(field,item) in spec.items():
                result=answers[key]['choice'];eid=answers[key+':evidence']['choice']
                checks.append(SemanticCheck(id=key,candidate_id=item.candidate.id if item else None,version_id=item.candidate.version_id if item else None,field=field,result=result,evidence_id=eid))
                if result!='MATCH':out.append(finding(data.core,result,'SEMANTIC_'+result,field,'Independent raw-source whole graph check',item=item,evidence_ids=(eid,)))
        except (ValueError,TypeError,AttributeError,OverflowError):out.append(finding(data.core,'CONTRACT_ERROR','INVALID_MIXED_OBSERVER','INPUT','Bounded observer contract failed'))
    elif not out:out.append(finding(data.core,'UNRESOLVED','INDEPENDENT_OBSERVATION_REQUIRED','JOINT_BINDINGS','Source spans alone do not prove mixed graph meaning'))
    priority={'MATCH':0,'UNRESOLVED':1,'DISCREPANCY':2,'CONTRACT_ERROR':3}
    return MixedSemanticDecision(result=max((f.result for f in out),key=priority.get,default='MATCH'),validation_input_sha256=content_sha256(data),observation=obs,checks=tuple(checks),findings=tuple(out))


def validate_mixed(data,provider=None):
    data=MixedSemanticInput.model_validate(data)
    prior=_findings(data)
    # Unresolved grounding must not prevent the independent observer detecting
    # a wrong whole graph. All prior findings remain in finalize; MATCH cannot
    # clear NOT_FOUND/ambiguity, and structural contract errors never call out.
    if provider is None or any(f.result=='CONTRACT_ERROR' for f in prior):return finalize(data,observation(data,{},{}))
    try:
        state,q,_=build_request(data)
        response=provider.decide(state=state,questions=q)
        return finalize(data,observation(data,{'state':state,'questions':q},response,provider.model))
    except (ValueError,TypeError,OSError,TimeoutError,OverflowError):return finalize(data,observation(data,{}, {'error_class':'MIXED_OBSERVER_STOP'},getattr(provider,'model',None)))


def assess_gate(data,decision):
    data=MixedSemanticInput.model_validate(data);decision=MixedSemanticDecision.model_validate(decision)
    result=decision.result if finalize(data,decision.observation)==decision else 'CONTRACT_ERROR'
    return MixedSemanticGate(state='ELIGIBLE_FOR_BUSINESS_CHECKS' if result=='MATCH' else 'FROZEN',result=result,input_sha256=content_sha256(data),decision_sha256=content_sha256(decision))
