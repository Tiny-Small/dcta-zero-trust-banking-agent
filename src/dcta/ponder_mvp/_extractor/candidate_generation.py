"""Dependency-light evidence proposals. Never imports annotations or a model/provider."""
import re
from typing import get_args
from pydantic import Field, model_validator
from .schema import Contract, Role
from .normalization import CURRENCIES, WORDS, number

GENERATOR_VERSION = "candidate-v2"
MAX_NOUN_WINDOW = 4
MAX_NUMBER_WORDS = 12
TOKEN = re.compile(r"US\$|S\$|\$|\d+(?:,\d{3})*(?:\.\d+)?(?:/\d+)?|[^\W\d_]+(?:['’\-][^\W\d_]+)*|%|[^\s]", re.UNICODE)
WORD = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*\Z", re.UNICODE)
DIGITS = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?\Z")
NUMBER_WORDS = set(WORDS) | {"hundred", "thousand", "and", "a", "grand"}
STOP = set(("send transfer move pay remit buy purchase sell invest cancel explain use make "
            "sent needs please could you do not never don't don’t actually no instead then "
            "from to in of and or but the my a an as for that’s is are was were will be "
            "if what how yesterday used between around about approximately").split())
ACCOUNT_WORDS = {"account", "accounts", "wallet", "fund", "savings", "checking", "balance"}
ASSET_WORDS = {"shares", "share", "stock", "stocks", "units", "unit", "etf", "security", "securities"}

ROLE_TYPES = {
    "transfer_amount": {"number", "money", "amount_expression"},
    "currency": {"currency"},
    "source_account": {"account_like", "noun_phrase", "name_like"},
    "destination_account": {"account_like", "noun_phrase", "name_like"},
    "beneficiary": {"name_like", "noun_phrase", "account_like"},
    "asset_quantity": {"number", "money"},
    "asset": {"asset_like", "name_like", "noun_phrase"},
    "percentage": {"percentage"},
    "fraction": {"fraction"},
    "dependent_amount": {"amount_expression", "reference_expression", "fraction", "percentage", "relational_expression"},
    "payment_reference": {"quoted", "noun_phrase"},
}

class Candidate(Contract):
    candidate_id: str
    text: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    candidate_types: list[str]
    generators: list[str]

    @model_validator(mode="after")
    def interval(self):
        if self.end <= self.start or len(self.text) != self.end - self.start:
            raise ValueError("candidate interval must match nonempty text length")
        if not self.candidate_types or not self.generators:
            raise ValueError("candidate types and provenance are required")
        return self

def eligible_candidates(candidates: list[Candidate], role: str) -> list[Candidate]:
    if role not in ROLE_TYPES:
        raise ValueError("unknown role")
    return [c for c in candidates if set(c.candidate_types) & ROLE_TYPES[role]]

def generate_candidates(text: str) -> list[Candidate]:
    """Only source text enters discovery. Exact duplicates merge provenance."""
    proposals = {}
    tokens = list(TOKEN.finditer(text))

    def add(start, end, types, generator):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start == end:
            return
        if not 0 <= start < end <= len(text):
            raise ValueError("generator produced invalid bounds")
        found = proposals.setdefault((start, end), [set(), set()])
        found[0].update(types)
        found[1].add(generator)

    # Numeric tokens and supported English scalar phrases, including internal variants.
    for token in tokens:
        value = token.group()
        if DIGITS.fullmatch(value):
            add(token.start(), token.end(), {"number"}, "numeric_token")
        if re.fullmatch(r"\d+/\d+", value):
            add(token.start(), token.end(), {"fraction"}, "fraction")
        if value.upper() in CURRENCIES or value == "$":
            add(token.start(), token.end(), {"currency"}, "currency")
    for i, token in enumerate(tokens):
        if token.group().lower() not in NUMBER_WORDS:
            continue
        for end in range(i + 1, min(len(tokens), i + MAX_NUMBER_WORDS) + 1):
            if tokens[end - 1].group().lower() not in NUMBER_WORDS:
                break
            quote = text[token.start():tokens[end - 1].end()]
            if number(quote) is not None:
                add(token.start(), tokens[end - 1].end(), {"number"}, "number_words")

    numeric = [span for span, info in proposals.items() if "number" in info[0]]
    currencies = [span for span, info in proposals.items() if "currency" in info[0]]
    for ns, ne in numeric:
        for cs, ce in currencies:
            if ce <= ns and not text[ce:ns].strip():
                add(cs, ne, {"money"}, "currency_number")
            if ne <= cs and not text[ne:cs].strip():
                add(ns, ce, {"money"}, "currency_number")
        suffix = re.match(r"\s*(?:%|percent\b)", text[ne:], re.I)
        if suffix:
            add(ns, ne + suffix.end(), {"percentage"}, "percentage")
    for match in re.finditer(r"\b(?:three\s+quarters|one\s+half|a\s+half|a\s+quarter|half|quarter)\b", text, re.I):
        add(match.start(), match.end(), {"fraction"}, "fraction")

    # Keep anaphoric evidence as a proposal; do not resolve what it refers to.
    for match in re.finditer(r"\b(?:it|that|this|those|these)\b", text, re.I):
        add(match.start(), match.end(), {"reference_expression"}, "anaphoric_reference")

    # Preserve correction directives without deciding their monetary interpretation.
    for match in re.finditer(
        r"\b(?:swap|reverse|exchange|switch)\s+(?:(?:the|these|those|our|my)\s+)?"
        r"(?:accounts?|directions?|roles?|amounts?|payments?)\b", text, re.I
    ):
        add(match.start(), match.end(), {"relational_expression"}, "relation_directive")

    # Expression boundaries terminate at punctuation or a new recipient/asset/clause.
    def expression_end(start):
        tail = text[start:]
        boundary = re.search(r"[.;,!?]|\s+(?:to|in|and|but|then)\b", tail, re.I)
        return start + boundary.start() if boundary else len(text)

    fraction_percent = [span for span, info in proposals.items() if info[0] & {"fraction", "percentage"}]
    for start, end in fraction_percent:
        of = re.match(r"\s+of\b", text[end:], re.I)
        if of:
            add(start, expression_end(end + of.end()), {"amount_expression"}, "dependent_of")
    for match in re.finditer(r"\b(?:the\s+)?remaining\s+(?:amount|balance|money)\b", text, re.I):
        add(match.start(), match.end(), {"amount_expression"}, "remaining_amount")
    for match in re.finditer(r"\b(?:around|about|approximately)\s+", text, re.I):
        for ns, ne in numeric:
            if ns == match.end():
                add(match.start(), ne, {"amount_expression"}, "approximation")
    for a, b in numeric:
        for c, d in numeric:
            if b < c and re.fullmatch(r"\s+or\s+", text[b:c], re.I):
                add(a, d, {"amount_expression"}, "numeric_alternative")
            if b < c and re.fullmatch(r"\s+and\s+", text[b:c], re.I):
                prefix = re.search(r"\bbetween\s*$", text[:a], re.I)
                if prefix:
                    add(prefix.start(), d, {"amount_expression"}, "numeric_range")

    for match in re.finditer(r"(?<!\w)(['\"])(.*?)\1(?!\w)|“([^”]+)”|‘([^’]+)’", text, re.S):
        group = 2 if match.group(2) is not None else 3 if match.group(3) is not None else 4
        add(match.start(group), match.end(group), {"quoted"}, "quotation")

    # Bounded local noun windows plus whole chunks, without a heavy syntactic parser.
    def is_noun_token(token):
        value = token.group()
        return bool(WORD.fullmatch(value)) and value.lower() not in STOP and value.lower() not in NUMBER_WORDS and value.upper() not in CURRENCIES

    def noun_run(run):
        if not run:
            return
        for i in range(len(run)):
            for j in range(i + 1, min(len(run), i + MAX_NOUN_WINDOW) + 1):
                add(run[i].start(), run[j - 1].end(), {"noun_phrase"}, "noun_chunks")
        add(run[0].start(), run[-1].end(), {"noun_phrase"}, "whole_noun_chunk")
        for i, token in enumerate(run):
            if not token.group()[0].isupper():
                continue
            for j in range(i + 1, len(run) + 1):
                if not run[j - 1].group()[0].isupper():
                    break
                add(token.start(), run[j - 1].end(), {"name_like"}, "proper_name")

    run = []
    for token in tokens:
        if is_noun_token(token) and (not run or not text[run[-1].end():token.start()].strip()):
            run.append(token)
        else:
            noun_run(run)
            run = [token] if is_noun_token(token) else []
    noun_run(run)

    # Retain both minimal and determiner-bearing variants of discovered noun phrases.
    for (start, end), info in list(proposals.items()):
        if "noun_phrase" not in info[0]:
            continue
        prefix = re.search(r"\b(?:a|an|the|my|our|their|your)\s+$", text[:start], re.I)
        if prefix:
            add(prefix.start(), end, set(info[0]), "determiner_variant")

    # Qualify discovered phrases, without excluding competing role eligibility.
    for (start, end), info in proposals.items():
        if "noun_phrase" not in info[0]:
            continue
        words = {t.group().lower() for t in TOKEN.finditer(text[start:end])}
        if words & ACCOUNT_WORDS:
            info[0].add("account_like")
            info[1].add("account_lexicon")
        if words & ASSET_WORDS:
            info[0].add("asset_like")
            info[1].add("asset_lexicon")
    return [Candidate(candidate_id=f"c{i}", text=text[start:end], start=start, end=end,
                      candidate_types=sorted(info[0]), generators=sorted(info[1]))
            for i, ((start, end), info) in enumerate(sorted(proposals.items()), 1)]
