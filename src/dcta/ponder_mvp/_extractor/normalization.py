"""Small, explicit deterministic policy; does not decide roles or intent."""
import re
from decimal import Decimal, InvalidOperation, localcontext
from .schema import Normalized

CURRENCIES={c:c for c in ("SGD","USD","EUR","GBP","JPY","MYR","AUD","HKD","CNY")}
CURRENCIES.update({"S$":"SGD","US$":"USD"})
WORDS={"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
       "eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12,"thirteen":13,
       "fourteen":14,"fifteen":15,"sixteen":16,"seventeen":17,"eighteen":18,
       "nineteen":19,"twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,
       "seventy":70,"eighty":80,"ninety":90}

def canonical(value: Decimal) -> str:
    if not value:return "0"
    text=format(value,"f")
    return text.rstrip("0").rstrip(".") if "." in text else text

def number(text: str) -> str | None:
    text=text.strip().lower()
    if text=="a grand": return "1000"
    if re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?",text):
        try:
            return canonical(Decimal(text.replace(",","")))
        except InvalidOperation:
            return None
    # Only a documented small English grammar, never approximation/range parsing.
    parts=text.replace("-"," ").split()
    total=current=0
    previous=None
    seen_thousand=False
    for word in parts:
        if word in WORDS:
            value=WORDS[word]
            if previous in WORDS and not (WORDS[previous]>=20 and value<10): return None
            current+=value
        elif word=="hundred" and previous in WORDS and 0<current<10:
            current*=100
        elif word=="thousand" and current>0 and not seen_thousand:
            seen_thousand=True
            total+=current*1000
            current=0
        elif word=="and" and previous in ("hundred","thousand"):
            pass
        else: return None
        previous=word
    return str(total+current) if parts and previous in (*WORDS,"hundred","thousand") else None

def normalize(role: str, text: str) -> Normalized:
    literal=text.strip()
    if role=="currency":
        return Normalized(kind="currency",value=CURRENCIES.get(literal.upper()))
    if role in ("transfer_amount","asset_quantity"):
        # Prefix currency signs are explicit surface text, never a default code.
        numeric=re.sub(r"^(?:SGD|USD|EUR|GBP|JPY|MYR|AUD|HKD|CNY|US\$|S\$|\$)\s*", "", literal,flags=re.I)
        return Normalized(kind="decimal",value=number(numeric))
    if role=="percentage":
        n=number(re.sub(r"(?:%|\s+percent)$","",literal,flags=re.I))
        with localcontext() as context:
            context.prec=max(28,len(n or "")+10)
            return Normalized(kind="percentage",value=canonical(Decimal(n)/100) if n is not None else None)
    if role=="fraction":
        values={"half":"0.5","a half":"0.5","one half":"0.5","a quarter":"0.25","quarter":"0.25","three quarters":"0.75"}
        value=values.get(literal.lower())
        if value is None and re.fullmatch(r"\d+/\d+",literal):
            a,b=literal.split("/")
            if int(b) and int(b) in (2,4,5,8,10,20,25,100):
                with localcontext() as context:
                    context.prec=max(28,len(a)+10)
                    value=canonical(Decimal(a)/Decimal(b))
        return Normalized(kind="fraction",value=value)
    if role=="dependent_amount": return Normalized(kind="expression",value=None)
    return Normalized(kind="text",value=literal)


def supported_normalization(role,text,value):
    expected=normalize(role,text)
    if value.kind!=expected.kind:return False
    if expected.value is None:return value.value is None
    if expected.kind in ("decimal","fraction","percentage"):
        try:return value.value is not None and Decimal(value.value).is_finite() and Decimal(value.value)==Decimal(expected.value)
        except (InvalidOperation,ValueError):return False
    return value.value==expected.value
