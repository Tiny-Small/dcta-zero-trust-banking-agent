"""High-recall literal cue proposals. No discourse, binding or intent answers."""
import re
from dcta.ponder.input import RelationalAnchor,EvidenceRef

PATTERNS={
 'PREDICATE':r"\b(?:send|sent|transfer(?:red)?|move(?:d)?|pay|paid|give|gave|buy|bought|sell|sold|invest(?:ed)?)\b|\b(?:set|update|change|use)\s+(?:(?:the|my)\s+)?(?:memo|reference)\b|\buse\b(?=[^.;]*\b(?:memo|reference)\b)",
 'COORDINATION':r"\b(?:and|or|each|both|either)\b",
 'CORRECTION':r"\b(?:actually|instead|rather|replace|change|make it|use)\b",
 'NEGATION':r"\b(?:do not|don't|dont|not|never|cancel)\b",
 'DISCOURSE':r"\b(?:yesterday|previously|earlier|last\s+\w+|suppose|imagine|hypothetically|now|today)\b",
 'REFERENCE':r"\b(?:same amount|other account|him|her|it|that|them|again)\b",
 'BASIS':r"\b(?:of\s+)?(?:the\s+)?(?:proceeds|balance|remainder|whatever is left|what is left)\b",
 'CONDITION':r"\b(?:if|unless|when|provided)\b[^.;]*",
 'NESTING':r"'[^']*'|\"[^\"]*\"",
}

def discover_anchors(source):
    found=[]
    for kind,pattern in PATTERNS.items():
        for m in re.finditer(pattern,source.text,re.I):
            found.append(RelationalAnchor(id=f'a:{kind}:{m.start()}:{m.end()}',kind=kind,
                evidence=EvidenceRef(source_id=source.id,start=m.start(),end=m.end(),text=m.group())))
    # Source-only preference fallback: one operation hypothesis anchored by
    # literal use; semantic goal is selected separately (unknown, not transfer).
    if not any(a.kind=='PREDICATE' for a in found):
        cue=next((a for a in found if a.kind=='CORRECTION' and a.evidence.text.lower()=='use'),None)
        if cue:found.append(RelationalAnchor(id=f'a:PREDICATE:{cue.evidence.start}:{cue.evidence.end}',kind='PREDICATE',evidence=cue.evidence))
    return tuple(sorted(found,key=lambda a:(a.evidence.start,a.evidence.end,a.kind)))
