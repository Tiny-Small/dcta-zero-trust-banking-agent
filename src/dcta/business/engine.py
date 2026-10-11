"""Deterministic business observation. No repair, hosted inference or services."""
from dcta.ponder.serialization import content_sha256
from .input import BusinessValidationInput,integrity_errors
from .records import BusinessValidationResult
from .checks import check_operation,aggregate_funds,combine,finding,velocity_findings


def validate_business(data):
    data=BusinessValidationInput.model_validate(data)
    errors=integrity_errors(data);operations=();findings=();ledger=()
    if errors:
        findings=tuple(finding(data,'CONTRACT_ERROR','BUSINESS_INPUT_INTEGRITY','INPUT',error,'Input/semantic admission/hash contract failed before banking rules') for error in errors)
        status='CONTRACT_ERROR'
    else:
        operations=[];fundings=[]
        for item,target in zip(data.candidates,data.targets):
            op,funding=check_operation(data,item,target);operations.append(op);fundings.append(funding)
        operations,ledger=aggregate_funds(data,operations,fundings)
        findings=velocity_findings(data,fundings)
        status=combine([*(op.status for op in operations),*(f.result for f in findings)])
    return BusinessValidationResult(funds_ledger=ledger,status=status,business_input_sha256=content_sha256(data),bundle_sha256=data.bundle_sha256,compilation_sha256=data.compilation_sha256,grounding_sha256=data.grounding_sha256,grounding_revision=data.grounding_revision,
        semantic_input_sha256=data.semantic_input_sha256,semantic_decision_sha256=data.semantic_decision_sha256,semantic_gate_sha256=data.semantic_gate_sha256,
        bank_sha256=data.bank_sha256,bank_version=data.bank.version,bank_revision=data.bank.revision,policy_sha256=data.policy_sha256,policy_version=data.policy.version,operations=tuple(operations),findings=findings)
