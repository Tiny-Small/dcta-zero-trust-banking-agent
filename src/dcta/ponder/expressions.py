"""Retain supplied symbolic structure; no arithmetic or antecedent selection."""
from collections import defaultdict
from .relations import OperandOfClaim, RefersToClaim
from .ir import ValueExpression, UnresolvedReference, CompilationIssue, ExpressionAssembly
from .integrity import all_mentions,all_anchors,all_scopes
from .serialization import content_sha256


def assemble_expressions(snapshot,bundle,discourse,integrity) -> ExpressionAssembly:
    if integrity.global_error:return ExpressionAssembly()
    mentions={m.id:m for m in all_mentions(snapshot)};anchors={a.id:a for a in all_anchors(snapshot)};scopes={p.mention_id:p for p in all_scopes(snapshot)}
    expressions=[];references=[];issues=[];operands=defaultdict(list)
    for m in sorted(mentions.values(),key=lambda m:m.id):
        expressions.append(ValueExpression(id="source:"+m.id,kind="DEPENDENT_SOURCE" if m.role=="dependent_amount" else "LITERAL_SOURCE",mention_id=m.id))
    valid=[c for c in bundle.claims if c.id not in integrity.blocked_relation_ids]
    for c in valid:
        if isinstance(c,OperandOfClaim):
            operands[c.parent_mention_id].append(c)
            scope=scopes.get(c.operand_mention_id)
            if scope and scope.producer_scope in {"ROOT","ROOT_EMITTED"}:
                issues.append(CompilationIssue(category="OPERAND_SCOPE_DISAGREEMENT",affected_ids=(c.operand_mention_id,),support_ids=(c.id,),severity="DIAGNOSTIC"))
    for parent,relations in sorted(operands.items()):
        params={c.parameter for c in relations}
        kind="RANGE" if "RANGE_ENDPOINT" in params else "ALTERNATIVE" if "ALTERNATIVE_VALUE" in params else "DEPENDENT_SOURCE"
        expressions.append(ValueExpression(id="operand:"+parent,kind=kind,mention_id=parent,operand_ids=tuple(sorted({c.operand_mention_id for c in relations})),support_ids=tuple(sorted(c.id for c in relations))))
    noncurrent=set()
    projections={p.candidate_id:p for p in discourse.projections}
    for candidate in discourse.candidates:
        projection=projections.get(candidate.id)
        if projection and projection.intent_status=="NOT_CURRENT":
            noncurrent.update(m for b in candidate.bindings for m in b.mention_ids)
    if snapshot.prior_context:
        for v in snapshot.prior_context.versions:
            if v.id in projections and projections[v.id].intent_status=="NOT_CURRENT":noncurrent.update(m for f in v.fields for m in f.mention_ids)
    for c in sorted(valid,key=lambda c:c.id):
        if not isinstance(c,RefersToClaim):continue
        antecedents=tuple(sorted(set(c.antecedent_ids)));basis=anchors[c.reference_anchor_id].kind=="BASIS"
        forbidden=any(id in noncurrent or (id in scopes and scopes[id].producer_scope in {"NESTED_DATA","EXCLUDED_BY_SCOPE"}) for id in antecedents) and not c.allow_noncurrent_antecedent
        reason="MISSING_CARRIER" if c.carrier_mention_id is None else "UNSUPPORTED_BASIS" if forbidden or (basis and not antecedents) else "NO_ANTECEDENT" if not antecedents else "MULTIPLE_ANTECEDENTS" if len(antecedents)>1 else None
        if c.requested_field=="OPERATION_TARGET":
            reason="NO_ANTECEDENT" if not c.antecedent_version_targets else "MULTIPLE_ANTECEDENTS" if len(c.antecedent_version_targets)>1 else None
        if reason:
            references.append(UnresolvedReference(id=c.id,anchor_id=c.reference_anchor_id,carrier_mention_id=c.carrier_mention_id,requested_field=c.requested_field,antecedent_ids=antecedents,antecedent_version_targets=c.antecedent_version_targets,reason=reason,support_ids=(c.id,)))
        if forbidden:issues.append(CompilationIssue(category="REFERENCE_SCOPE_CONFLICT",affected_ids=antecedents,support_ids=(c.id,),severity="UNRESOLVED"))
        carrier=mentions.get(c.carrier_mention_id)
        kind="DEPENDENT_SOURCE" if basis and carrier and carrier.role=="dependent_amount" else "UNRESOLVED" if reason else "REFERENCE"
        expressions.append(ValueExpression(id="ref:"+c.id,kind=kind,mention_id=c.carrier_mention_id,basis_anchor_ids=(c.reference_anchor_id,) if basis else (),antecedent_ids=antecedents,antecedent_version_targets=c.antecedent_version_targets,support_ids=(c.id,)))
    return ExpressionAssembly(expressions=tuple(sorted(expressions,key=lambda e:e.id)),references=tuple(sorted(references,key=lambda r:r.id)),issues=tuple(sorted(issues,key=content_sha256)))
