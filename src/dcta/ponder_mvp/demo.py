"""20-case hackathon smoke; no held-out/benchmark access, no hosted retry."""
import argparse,hashlib,json,math,time
from pathlib import Path
from .pipeline import assemble_text
from ._extractor.providers.decisions import DecisionsProvider,read_settings

ROOT=Path(__file__).resolve().parents[3]
CASES=ROOT/'docs/ponder/MVP_CASES.json'

class StopRun(RuntimeError):pass


def load_cases():return json.loads(CASES.read_text())['cases']


def create_output(path):
    path=Path(path);path.mkdir(parents=True,exist_ok=False);return path


def source_hashes():
    paths=list((ROOT/'src').rglob('*.py'))+[CASES,ROOT/'docs/ponder/MVP_EXTRACTOR_SOURCE_MANIFEST.json',ROOT/'docs/ponder/PONDER_MILESTONE_MANIFEST.json']
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def verify_foundation():
    manifest=json.loads((ROOT/'docs/ponder/PONDER_MILESTONE_MANIFEST.json').read_text())
    for f,h in manifest['source_and_artifact_sha256'].items():
        if hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=h:raise StopRun('frozen milestone source drift')
    copied=json.loads((ROOT/'docs/ponder/MVP_EXTRACTOR_SOURCE_MANIFEST.json').read_text())
    for f,record in copied['files'].items():
        if hashlib.sha256(Path(record['dev_path']).read_bytes()).hexdigest()!=record['sha256'] or hashlib.sha256((Path(copied['source_root'])/f).read_bytes()).hexdigest()!=record['sha256']:
            raise StopRun('frozen extractor source drift')

class GuardedProvider:
    def __init__(self,provider,*,max_requests,max_questions,cost_stop,hashes,journal):
        self.provider=provider;self.model=provider.model;self.max_requests=max_requests;self.max_questions=max_questions
        self.cost_stop=cost_stop;self.hashes=hashes;self.journal=Path(journal)
        self.requests=0;self.questions=0;self.cost=0.;self.latencies=[]
    def decide(self,*,state,questions):
        if self.requests>=self.max_requests or self.questions+len(questions)>self.max_questions or self.cost>=self.cost_stop:
            raise StopRun('request/question/cost budget stop')
        for path,h in self.hashes.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=h:raise StopRun('source drift before transport')
        response=self.provider.decide(state=state,questions=questions)
        self.requests+=1;self.questions+=len(questions);self.latencies.append(response.get('latency_ms',0))
        with self.journal.open('a') as f:f.write(json.dumps({'request_index':self.requests,'response':response},ensure_ascii=False,allow_nan=False)+'\n')
        envelope=response.get('raw_response');usage=envelope.get('usage',{}) if isinstance(envelope,dict) else {}
        cost=usage.get('cost') if isinstance(usage,dict) else None
        if type(cost) not in (float,int) or not math.isfinite(cost) or cost<0:raise StopRun('missing/invalid measured cost; response saved')
        self.cost+=cost
        return response


def _financial_view(compilation):
    mentions={m['id']:m for m in compilation['input_snapshot']['semantic_mentions']}
    current=set(compilation['current_candidate_ids']);rows=[]
    for c in compilation['candidates']:
        if c['id'] not in current:continue
        row={'goal':c['goal']}
        for b in c['bindings']:
            if b['mention_ids']:
                texts=[mentions[mid]['evidence']['text'] for mid in b['mention_ids'] if mid in mentions]
                row[b['field']]=texts[0] if len(texts)==1 else texts
        rows.append(row)
    return rows


def check_case(case,result):
    expected=case['expect'];ponder=result.get('ponder') or {};comp=ponder.get('compilation')
    if not comp or result.get('status')!='OK':return {'passed':False,'failures':[result.get('status','no_compilation')],'actual_current':[]}
    actual=_financial_view(comp);failures=[]
    current=set(comp['current_candidate_ids'])
    for candidate in comp['candidates']:
        if candidate['id'] not in current:continue
        for binding in candidate['bindings']:
            if not binding['mention_ids']:continue
            allowed_symbolic=expected.get('symbolic') and binding['field']=='AMOUNT' and binding['status']=='UNRESOLVED'
            if binding['status']!='BOUND' and not allowed_symbolic:failures.append('unresolved current field: '+binding['field'])
    if any(i['severity']=='ERROR' or i['category']=='SCOPE_USAGE_CONFLICT' for i in comp['issues']):failures.append('representation/scope conflict')
    # Match full current field inventory, not merely count of candidates.
    key=lambda r:json.dumps(r,sort_keys=True)
    if sorted(map(key,actual))!=sorted(map(key,expected['current'])):failures.append('current operation/field graph')
    if expected.get('allocation_unresolved'):
        groups=[g for g in comp['groups'] if g['kind']=='EXCLUSIVE' and {b['allocation'] for b in g['branches']}=={'TOTAL_UNALLOCATED','PER_RECIPIENT'}]
        if not groups or not comp['requested_group_ids']:failures.append('allocation ambiguity')
    if expected.get('shared_amount') and not any(c['kind']=='SHARED_FIELD' and c['field']=='AMOUNT' and c['mode']=='DISTRIBUTIVE' for c in comp['relation_bundle']['claims']):failures.append('explicit each sharing')
    if expected.get('replacement_field') and not any(r['kind']=='REPLACES' and r['target']['kind']=='FIELD' and r['target']['field']==expected['replacement_field'] for r in comp['revisions']):failures.append('typed correction')
    if expected.get('rejected_field') and not any(r['kind']=='REJECTS' and r['target']['kind']=='FIELD' and r['target']['field']==expected['rejected_field'] for r in comp['revisions']):failures.append('local rejection')
    if expected.get('context') and not any(p['context']==expected['context'] for p in comp['projections']):failures.append('retained discourse')
    if expected.get('noncurrent') and not any(p['intent_status']=='NOT_CURRENT' for p in comp['projections']):failures.append('noncurrent preservation')
    if expected.get('symbolic'):
        mentions={m['id']:m for m in comp['input_snapshot']['semantic_mentions']}
        claims=comp['relation_bundle']['claims']
        operands=[c for c in claims if c['kind']=='OPERAND_OF' and mentions[c['operand_mention_id']]['role'] in ('fraction','percentage') and mentions[c['parent_mention_id']]['role']=='dependent_amount']
        bases=[e for e in comp['expressions'] if e['basis_anchor_ids'] and e['mention_id'] and mentions[e['mention_id']]['role']=='dependent_amount']
        if not operands or not bases:failures.append('explicit symbolic operand/basis')
    if expected.get('condition') and not any(p['condition_anchor_ids'] for p in comp['projections']):failures.append('condition attachment')
    return {'passed':not failures,'failures':failures,'actual_current':actual}


def distribution(values):
    if not values:return {'p50':None,'p95':None,'max':None}
    values=sorted(values)
    return {'p50':values[math.ceil(len(values)*.50)-1],'p95':values[math.ceil(len(values)*.95)-1],'max':values[-1]}


def run(output,settings):
    verify_foundation();hashes=source_hashes();key,model=read_settings(Path(settings))
    if model!='typesafe/jev-1.13':raise StopRun('MVP pinned model mismatch')
    out=create_output(output)
    freeze={'version':'ponder-mvp-first-pass-v1','cases_sha256':hashlib.sha256(CASES.read_bytes()).hexdigest(),
        'runtime_sha256':hashes,'model':model,'provider':'TypeSafe','max_requests':120,'max_questions':1000,'cost_stop_usd':1,
        'protocol':'20 targeted development cases; one observation; no retry; no gold request pruning; no generalization claim'}
    (out/'freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
    provider=GuardedProvider(DecisionsProvider(key,model=model),max_requests=120,max_questions=1000,cost_stop=1,hashes=hashes,journal=out/'requests.jsonl')
    rows=[];stopped=None
    for case in load_cases():
        try:
            result=assemble_text(case['text'],provider,source_id=case['id'])
            row={'id':case['id'],'scenario':case['scenario'],'result':result,'check':check_case(case,result)}
            rows.append(row)
            with (out/'observations.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
            print(json.dumps({'id':case['id'],'scenario':case['scenario'],'status':result['status'],'passed':row['check']['passed'],'packets':(result.get('ponder') or {}).get('registry',{}).get('counts')},ensure_ascii=False),flush=True)
        except StopRun as e:stopped={'id':case['id'],'reason':str(e)};break
    verify_foundation()
    summary={'completed':len(rows),'passed':sum(r['check']['passed'] for r in rows),'stopped':stopped,'http_requests':provider.requests,'questions':provider.questions,'cost_usd':provider.cost,
        'latency_ms':{'http':distribution(provider.latencies),'end_to_end':distribution([r['result']['latency_ms'] for r in rows])},
        'candidate_counts':distribution([len((r['result'].get('extraction') or {}).get('raw',{}).get('candidates',[])) for r in rows]),
        'packet_counts':distribution([dict((r['result'].get('ponder') or {}).get('registry',{}).get('counts',[])).get('packets',0) for r in rows]),
        'failures':[{'id':r['id'],'scenario':r['scenario'],'status':r['result']['status'],**r['check']} for r in rows if not r['check']['passed']],
        'frozen_source_verified':True,'protected_corpus_used':False,'retries':0}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--output',required=True)
    parser.add_argument('--settings',required=True)
    args=parser.parse_args()
    if not args.live:parser.error('Explicit --live required; no automatic inference')
    run(args.output,args.settings)

if __name__=='__main__':main()
