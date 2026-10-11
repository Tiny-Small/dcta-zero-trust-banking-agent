"""Hackathon path only; accepted compiler remains pure and unchanged."""
import time
from dcta.ponder.compiler import compile_intent
from .bridge import extract_text,snapshot_from_extraction
from .packets import build_registry
from .selection import build_request,parse_selection,emit_bundle


def assemble_snapshot(snapshot,provider):
    started=time.perf_counter();registry=build_registry(snapshot)
    result={'status':registry.status,'snapshot':snapshot.model_dump(mode='json'),'registry':registry.model_dump(mode='json'),
        'request':None,'response':None,'bundle':None,'compilation':None,'error':None}
    if registry.status!='READY':return result
    try:
        state,questions=build_request(snapshot,registry);result['request']={'state':state,'questions':questions}
        response=provider.decide(state=state,questions=questions);result['response']=response
        choices=parse_selection(response,questions,model=provider.model);result['choices']=choices
        if choices['binding']=='UNSUPPORTED' or any(v=='UNSUPPORTED' for k,v in choices.items() if k.startswith('anchor:')):
            result['status']='UNSUPPORTED';result['error']='semantic interpretation not offered';return result
        bundle=emit_bundle(snapshot,registry,choices);result['bundle']=bundle.model_dump(mode='json')
        compilation=compile_intent(snapshot,bundle);result['compilation']=compilation.model_dump(mode='json')
        result['status']=compilation.status
    except OverflowError as e:result.update(status='LIMIT_EXCEEDED',error=str(e))
    except ValueError as e:result.update(status='UNSUPPORTED' if str(e).startswith('UNSUPPORTED:') else 'POLICY_CONTRACT_ERROR',error=str(e))
    finally:result['latency_ms']=(time.perf_counter()-started)*1000
    return result


def assemble_text(text,provider,*,source_id='mvp-input'):
    started=time.perf_counter()
    result={'text':text,'source_id':source_id,'extraction':None,'ponder':None,'status':'UPSTREAM_ERROR','error':None}
    try:
        stages=extract_text(text,provider,source_id=source_id);result['extraction']=stages
        snapshot=snapshot_from_extraction(stages)
        result['ponder']=assemble_snapshot(snapshot,provider);result['status']=result['ponder']['status']
    except ValueError as e:result['error']=str(e)
    result['latency_ms']=(time.perf_counter()-started)*1000
    return result
