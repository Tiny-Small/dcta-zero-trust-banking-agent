"""Inspectable synthetic demo banking state. No customer data or services."""
from dcta.ponder.serialization import content_sha256
from dcta.ponder_mvp.grounding import mock_directory
from .records import *


def mock_policy():
    return MockBankPolicy(version='mock-risk-policy-v2',supported_goals=('transfer','payment'),currencies=(CurrencyRule(iso='SGD',minor_units=2,per_transaction_limit='1000.00'),CurrencyRule(iso='USD',minor_units=2,per_transaction_limit='500.00',daily_outgoing_limit='750.00')),trusted_condition_sources=(TrustedConditionSource(id='mock:reimbursement-feed',version='v1'),))


def mock_bank():
    directory=mock_directory()
    accounts=(BankAccount(entity_id='account:savings',owner_id='mock:user:demo',active=True,usable=True,supported_currencies=('SGD','USD'),balances=(Balance(currency='SGD',available='2000.00'),Balance(currency='USD',available='500.00'))),
        BankAccount(entity_id='account:reserve',owner_id='mock:user:demo',active=True,usable=True,supported_currencies=('SGD',),balances=(Balance(currency='SGD',available='200.00'),)),
        BankAccount(entity_id='account:joint',owner_id='mock:user:other',active=True,usable=True,supported_currencies=('SGD',),balances=(Balance(currency='SGD',available='750.00'),)))
    recipients=tuple(BankRecipient(entity_id=e.id,kind=e.kind,active=True,supported_currencies=('SGD','USD')) for e in directory.entities if e.kind=='PERSON')
    return MockBankState(version='mock-bank-state-v1',revision=0,snapshot_id='mock:bank-snapshot:000',authenticated_user_id='mock:user:demo',directory_sha256=content_sha256(directory),accounts=accounts,recipients=recipients)
