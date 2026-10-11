"""Conservative directive quarantine, not a complete injection classifier.

Normalization is detection-only. Original text/spans/hashes remain untouched.
"""
import re,unicodedata,html,hashlib
from dcta.ponder.base import FrozenRecord
VERSION='dcta-prompt-shield-v1'
RULES=(
 ('INSTRUCTION_OVERRIDE',r'\b(?:ignore|disregard|override|forget|replace|change)\b.{0,80}\b(?:previous|prior|above|system|developer|validator|policy|instructions?|prompt|rules?)\b'),
 ('FORCED_STATE',r'\b(?:return|output|respond|emit|set|mark|force|report|declare|pretend|treat)\b.{0,80}\b(?:match|pass|confirmed|authorized|validated|approved)\b'),
 ('GATE_BYPASS',r'\b(?:skip|bypass|disable|remove|avoid|waive)\b.{0,80}\b(?:confirmation|authorization|validation|clarification|gate|policy|limits?|checks?)\b'),
 ('TOOL_INVOCATION',r'\b(?:call|invoke|run|execute)\b.{0,32}\b(?:execute|tools?|function|bank|shell|api)\b|\bexecute\s*\('),
 ('ROLE_DELIMITER',r'(?:^|\n)\s*(?:system|developer|assistant|tool)\s*:|<\s*/?\s*(?:system|developer|assistant|tool|data)\b|\[\s*(?:im_start|inst)\s*\]'),
 ('STATE_OBJECT',r'["\']?(?:status|result|gate|confirmed|authorized)["\']?\s*[:=]\s*["\']?(?:authorized|confirmed|match|pass|true|eligible_for_confirmation)\b'),
 ('POLICY_OVERRIDE',r'\b(?:change|raise|remove|ignore|disable|override)\b.{0,60}\b(?:banking policy|risk policy|daily limit|transaction limit|velocity|balance check)\b'))
COMPILED=tuple((name,re.compile(pattern,re.I|re.S)) for name,pattern in RULES)

class ShieldFinding(FrozenRecord):
    rule: str
    path: str
    payload_sha256: str
    version: str=VERSION

class ShieldViolation(ValueError):
    def __init__(self,code,findings=()):
        super().__init__(code);self.code=code;self.findings=tuple(findings)


def inspect_strings(value):
    if isinstance(value,FrozenRecord):value=value.model_dump(mode='json')
    findings=[];count=0;size=0
    def flag(rule,path,text):findings.append(ShieldFinding(rule=rule,path=path,payload_sha256=hashlib.sha256(text.encode()).hexdigest()))
    def visit(v,path,depth):
        nonlocal count,size
        count+=1
        if depth>48 or count>10000:raise ShieldViolation('SHIELD_INPUT_LIMIT')
        if isinstance(v,str):
            try:encoded=v.encode("utf-8")
            except UnicodeEncodeError:raise ShieldViolation("SHIELD_INPUT_ENCODING") from None
            size+=len(encoded)
            if len(v)>65536 or size>300000:raise ShieldViolation('SHIELD_INPUT_LIMIT')
            normalized=unicodedata.normalize('NFKC',html.unescape(html.unescape(v)))
            normalized=''.join(c for c in normalized if unicodedata.category(c)!='Cf')
            for name,pattern in COMPILED:
                if pattern.search(normalized):flag(name,path,v)
        elif isinstance(v,dict):
            for key,item in v.items():
                visit(str(key),path+'.<key>',depth+1);visit(item,path+'.'+str(key),depth+1)
        elif isinstance(v,(list,tuple)):
            for n,item in enumerate(v):visit(item,path+'['+str(n)+']',depth+1)
        elif v is not None and type(v) not in (int,float,bool):raise ShieldViolation('SHIELD_INPUT_TYPE')
    visit(value,'$',0)
    return tuple(findings)


def require_clean(value):
    findings=inspect_strings(value)
    if findings:raise ShieldViolation('PROMPT_INJECTION_SHIELD_BLOCKED',findings)
