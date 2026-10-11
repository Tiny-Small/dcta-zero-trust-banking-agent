"""Benchmark contracts. Every string ID is a local association label, never a bank ID."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["transfer_amount", "currency", "source_account", "destination_account",
               "beneficiary", "asset_quantity", "asset", "percentage", "fraction",
               "dependent_amount", "payment_reference"]
State = Literal["active", "rejected", "superseded", "unresolved", "mentioned"]
Context = Literal["command", "historical", "hypothetical", "quoted", "negated", "ambiguous", "unknown"]
Intent = Literal["transfer", "payment", "investment", "unknown"]

class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class Evidence(Contract):
    text: str
    start: int | None = None
    end: int | None = None

class Normalized(Contract):
    kind: Literal["decimal", "currency", "text", "percentage", "fraction", "expression"]
    value: str | None = None

class Slot(Contract):
    role: Role
    evidence: Evidence
    normalized: Normalized | None = None
    state: State = "active"
    grounded_bank_id: None = None

class Operation(Contract):
    id: str
    intent: Intent = "unknown"
    context: Context = "unknown"
    state: State = "active"
    slots: list[Slot] = Field(default_factory=list)
    missing_roles: list[Role] = Field(default_factory=list)

class ExtractionResult(Contract):
    turn_id: str | None = None
    revision: int | None = None
    is_final: bool = True
    status: Literal["ok", "error", "unavailable"] = "ok"
    operations: list[Operation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error_message: str | None = None
    timings_ms: dict[str, float] = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_operations(self):
        ids=[o.id for o in self.operations]
        if len(ids)!=len(set(ids)):
            raise ValueError("duplicate operation IDs")
        return self

class Example(Contract):
    id: str
    text: str
    turn_id: str | None = None
    session_id: str | None = None
    revision: int | None = None
    is_final: bool = True
    annotation_status: Literal["candidate_synthetic", "human_reviewed"] = "candidate_synthetic"
    template_family: str
    tags: list[str] = Field(default_factory=list)
    notes: str = "Candidate annotation; human review required."
    gold: ExtractionResult
