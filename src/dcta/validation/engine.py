"""Hybrid validator: independent deterministic checks + separate semantic observation."""
import json
from dcta.ponder.serialization import content_sha256
from dcta.ponder_mvp._extractor.providers.decisions import parse_choices
from .input import ValidationInput
from .records import ValidationDecision,ValidationTarget,ValidatorObservation,SemanticCheck,VERSION,json_text,string_hash
from .checks import deterministic_findings,finding
from .semantic import build_request


def make_observation(data,mode,request,response,model=None):
    rq=json_text(request)
    try:rs=json_text(response)
    except (ValueError,TypeError,OverflowError):rs=json_text({'http_status':None,'error_class':'NON_JSON_VALIDATOR_OUTPUT'})
    return ValidatorObservation(mode=mode,validation_input_sha256=content_sha256(data),configured_model=model,request_json=rq,request_sha256=string_hash(rq),response_json=rs,response_sha256=string_hash(rs))


def finalize(data,observation):
    data=ValidationInput.model_validate(data);observation=ValidatorObservation.model_validate(observation)
    findings=list(deterministic_findings(data));checks=[]
    if observation.validation_input_sha256!=content_sha256(data) or observation.validator_version!=VERSION or observation.request_sha256!=string_hash(observation.request_json) or observation.response_sha256!=string_hash(observation.response_json):
        findings.append(finding(data,'CONTRACT_ERROR','OBSERVATION_INTEGRITY','INPUT','Independent observation hash/version mismatch'))
    elif observation.mode=='MODEL':
        try:
            state,questions,specs=build_request(data)
            if json.loads(observation.request_json)!={'state':state,'questions':questions}:raise ValueError('validator request mismatch')
            response=json.loads(observation.response_json);envelope=response.get('raw_response')
            if response.get('http_status')!=200 or response.get('error_class') or not isinstance(envelope,dict):raise ValueError('validator transport/shape error')
            resolved=envelope.get('model');model=observation.configured_model
            if not model or not isinstance(resolved,str) or not (resolved==model or resolved.startswith(model+'-')) or envelope.get('provider')!='TypeSafe':raise ValueError('validator model/provider mismatch')
            answers,errors=parse_choices(envelope,questions)
            if errors:raise ValueError('malformed independent validator choices')
            for key,(field,item) in specs.items():
                result=answers[key]['choice'];eid=answers[key+':evidence']['choice']
                checks.append(SemanticCheck(id=key,candidate_id=item.candidate.id if item else None,version_id=item.candidate.version_id if item else None,field=field,result=result,evidence_id=eid))
                if result!='MATCH':findings.append(finding(data,result,'SEMANTIC_'+result,field,questions[key]['instructions'],item=item,proposed=json_text(state['proposed_current_operations']),evidence_ids=(eid,)))
        except (ValueError,TypeError,AttributeError,OverflowError) as e:findings.append(finding(data,'CONTRACT_ERROR','INVALID_VALIDATOR_OUTPUT','INPUT',str(e)))
    elif not findings:
        findings.append(finding(data,'UNRESOLVED','INDEPENDENT_OBSERVATION_REQUIRED','JOINT_BINDINGS','Exact-span checks alone cannot validate operation count, discourse and joint interpretation'))
    priority={'MATCH':0,'UNRESOLVED':1,'DISCREPANCY':2,'CONTRACT_ERROR':3}
    result=max((f.result for f in findings),key=priority.get) if findings else 'MATCH'
    return ValidationDecision(result=result,validation_input_sha256=content_sha256(data),targets=tuple(ValidationTarget(candidate_id=x.candidate.id,frame_id=x.candidate.frame_id,version_id=x.candidate.version_id,candidate_sha256=content_sha256(x.candidate)) for x in data.targets),
        grounding_sha256=data.grounding_sha256,grounding_revision=data.grounding_revision,observation_sha256=content_sha256(observation),observation=observation,checks=tuple(checks),findings=tuple(findings))


def validate(data,provider=None):
    data=ValidationInput.model_validate(data);findings=deterministic_findings(data)
    if findings or provider is None:return finalize(data,make_observation(data,'DETERMINISTIC',{},{}))
    try:state,questions,_=build_request(data)
    except OverflowError as e:return finalize(data,make_observation(data,'MODEL',{}, {'http_status':None,'error_class':str(e)},getattr(provider,'model',None)))
    try:response=provider.decide(state=state,questions=questions)
    except (OSError,TimeoutError,ValueError) as e:response={'http_status':None,'error_class':type(e).__name__}
    return finalize(data,make_observation(data,'MODEL',{'state':state,'questions':questions},response,provider.model))
