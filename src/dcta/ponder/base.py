"""Closed immutable records; no mutable containers or unchecked constructors."""
from typing import Literal
from pydantic import BaseModel, ConfigDict

Role = Literal["transfer_amount", "dependent_amount", "beneficiary", "source_account", "destination_account", "currency", "asset", "asset_quantity", "fraction", "percentage", "payment_reference"]
Field = Literal["AMOUNT", "BENEFICIARY", "SOURCE_ACCOUNT", "DESTINATION_ACCOUNT", "CURRENCY", "ASSET", "QUANTITY", "REFERENCE"]
ReferenceField = Field | Literal["OPERATION_TARGET"]
Goal = Literal["transfer", "payment", "investment", "reference_update", "unknown"]
Context = Literal["command", "historical", "hypothetical", "quoted", "negated", "ambiguous", "unknown"]
Disposition = Literal["active", "rejected", "superseded", "unresolved", "mentioned"]
IntentStatus = Literal["PROPOSED", "UNRESOLVED", "NOT_CURRENT"]
FIELDS = ("AMOUNT", "BENEFICIARY", "SOURCE_ACCOUNT", "DESTINATION_ACCOUNT", "CURRENCY", "ASSET", "QUANTITY", "REFERENCE")
ROLE_FIELDS = {"AMOUNT": frozenset({"transfer_amount", "dependent_amount"}), "BENEFICIARY": frozenset({"beneficiary"}), "SOURCE_ACCOUNT": frozenset({"source_account"}), "DESTINATION_ACCOUNT": frozenset({"destination_account"}), "CURRENCY": frozenset({"currency"}), "ASSET": frozenset({"asset"}), "QUANTITY": frozenset({"asset_quantity"}), "REFERENCE": frozenset({"payment_reference"})}

class FrozenRecord(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", revalidate_instances="always")

    @classmethod
    def model_construct(cls, **kwargs):
        raise TypeError("Unchecked construction is forbidden")

    def model_copy(self, **kwargs):
        raise TypeError("Use validated reconstruction, never unchecked copy/update")
