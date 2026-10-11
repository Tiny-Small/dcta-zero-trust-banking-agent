"""Exact mock directory grounding; separate immutable version-bound results."""
from typing import Literal
from dcta.ponder.base import FrozenRecord,Field
from dcta.ponder.input import EvidenceRef
from dcta.ponder.serialization import content_sha256
from .consumer import ConsumerView,consume

class DirectoryEntity(FrozenRecord):
    id: str
    kind: Literal['PERSON','ACCOUNT','ASSET']
    name: str
    aliases: tuple[str,...]

class Directory(FrozenRecord):
    version: str
    entities: tuple[DirectoryEntity,...]

class GroundedField(FrozenRecord):
    id: str
    candidate_id: str
    frame_id: str
    version_id: str
    candidate_sha256: str
    snapshot_sha256: str
    bundle_sha256: str
    field: Field
    mention_id: str
    literal: str
    evidence: EvidenceRef
    status: Literal['RESOLVED','AMBIGUOUS','NOT_FOUND','UNRESOLVED_REFERENCE']
    matches: tuple[DirectoryEntity,...]=()
    selected_entity_id: str | None=None
    reason: str=''

class ClarificationChoice(FrozenRecord):
    id: str
    field_id: str
    prompt: str
    options: tuple[DirectoryEntity,...]

class GroundingDecision(FrozenRecord):
    choice_id: str
    field_id: str
    entity_id: str
    previous_state_sha256: str

class GroundingState(FrozenRecord):
    schema_version: Literal['ponder-grounding-v1']='ponder-grounding-v1'
    compilation_sha256: str
    consumer_sha256: str
    directory_sha256: str
    revision: int=0
    parent_sha256: str | None=None
    fields: tuple[GroundedField,...]
    clarifications: tuple[ClarificationChoice,...]=()
    decisions: tuple[GroundingDecision,...]=()
    limitations: tuple[str,...]=()

KINDS={'BENEFICIARY':'PERSON','SOURCE_ACCOUNT':'ACCOUNT','DESTINATION_ACCOUNT':'ACCOUNT','ASSET':'ASSET'}


def mock_directory():
    """Synthetic hackathon directory. No real bank/customer data or balances."""
    return Directory(version='mock-bank-v1',entities=(
        DirectoryEntity(id='person:sarah',kind='PERSON',name='Sarah Lee',aliases=('Sarah','Sarah Lee')),
        DirectoryEntity(id='person:john-tan',kind='PERSON',name='John Tan',aliases=('John','John Tan')),
        DirectoryEntity(id='person:john-lim',kind='PERSON',name='John Lim',aliases=('John','John Lim')),
        DirectoryEntity(id='person:jane',kind='PERSON',name='Jane Wong',aliases=('Jane','Jane Wong')),
        DirectoryEntity(id='account:savings',kind='ACCOUNT',name='Savings account',aliases=('savings','my savings','savings account')),
        DirectoryEntity(id='account:reserve',kind='ACCOUNT',name='Reserve account',aliases=('reserve','my reserve','reserve account')),
        DirectoryEntity(id='account:joint',kind='ACCOUNT',name='Joint account',aliases=('joint','joint account','my joint account')),
        DirectoryEntity(id='asset:dbs',kind='ASSET',name='DBS shares',aliases=('DBS','DBS shares'))))


def ground(view: ConsumerView,directory: Directory,*,max_choices=5) -> GroundingState:
    view=ConsumerView.model_validate(view);directory=Directory.model_validate(directory)
    if view.status!='OK':raise ValueError('consumer partial/contract state is blocked')
    if content_sha256(consume(view.compilation))!=content_sha256(view):raise ValueError('consumer integrity mismatch')
    if max_choices<2:raise ValueError('bounded clarification requires at least two choices')
    if len({e.id for e in directory.entities})!=len(directory.entities):raise ValueError('duplicate directory entity ID')
    fields=[];choices=[];limitations=[]
    for item in view.current:
        candidate=item.candidate;mentions={m.id:m for m in item.mentions}
        for binding in candidate.bindings:
            # Missing fields remain exposed on the consumer; no synthetic mention
            # or lookup request is created for an absent field.
            if binding.field not in KINDS and binding.status=='BOUND':continue
            for mid in binding.mention_ids:
                m=mentions[mid];fid=candidate.id+':'+binding.field+':'+mid
                matches=();selected=None;reason=''
                if binding.status!='BOUND':status='UNRESOLVED_REFERENCE';reason='Ponder binding '+binding.status
                elif binding.field not in KINDS:continue
                else:
                    literal=m.evidence.text.strip().casefold()
                    matches=tuple(sorted((e for e in directory.entities if e.kind==KINDS[binding.field] and literal in {a.strip().casefold() for a in (e.name,*e.aliases)}),key=lambda e:e.id))
                    status='NOT_FOUND' if not matches else 'RESOLVED' if len(matches)==1 else 'AMBIGUOUS'
                    if status=='RESOLVED':selected=matches[0].id
                    if status=='AMBIGUOUS':
                        if len(matches)>max_choices:limitations.append('LIMIT_EXCEEDED directory matches for '+fid)
                        else:choices.append(ClarificationChoice(id='entity:'+fid,field_id=fid,prompt='Which '+m.evidence.text+' do you mean?',options=matches))
                fields.append(GroundedField(id=fid,candidate_id=candidate.id,frame_id=candidate.frame_id,version_id=candidate.version_id,
                    candidate_sha256=content_sha256(candidate),snapshot_sha256=candidate.snapshot_sha256,bundle_sha256=candidate.bundle_sha256,
                    field=binding.field,mention_id=mid,literal=m.evidence.text,evidence=m.evidence,status=status,matches=matches,selected_entity_id=selected,reason=reason))
    return GroundingState(compilation_sha256=view.compilation_sha256,consumer_sha256=content_sha256(view),directory_sha256=content_sha256(directory),
        fields=tuple(fields),clarifications=tuple(choices),limitations=tuple(limitations))


def clarify(state,choice_id,entity_id,*,expected_state_sha256,expected_compilation_sha256):
    state=GroundingState.model_validate(state);previous=content_sha256(state)
    if previous!=expected_state_sha256 or state.compilation_sha256!=expected_compilation_sha256:raise ValueError('stale clarification state/candidate version')
    choice=next((c for c in state.clarifications if c.id==choice_id),None)
    if choice is None or entity_id not in {e.id for e in choice.options}:raise ValueError('entity choice not offered')
    fields=[];found=False
    for f in state.fields:
        if f.id==choice.field_id:
            if f.status!='AMBIGUOUS' or entity_id not in {e.id for e in f.matches}:raise ValueError('clarification field not ambiguous/offered')
            f=GroundedField.model_validate({**f.model_dump(),'status':'RESOLVED','selected_entity_id':entity_id});found=True
        fields.append(f)
    if not found:raise ValueError('clarification field missing')
    decision=GroundingDecision(choice_id=choice_id,field_id=choice.field_id,entity_id=entity_id,previous_state_sha256=previous)
    return GroundingState(compilation_sha256=state.compilation_sha256,consumer_sha256=state.consumer_sha256,directory_sha256=state.directory_sha256,
        revision=state.revision+1,parent_sha256=previous,fields=tuple(fields),clarifications=tuple(c for c in state.clarifications if c.id!=choice_id),decisions=state.decisions+(decision,),limitations=state.limitations)
