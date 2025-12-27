from __future__ import annotations

import re

# This MUST exist: app/main.py imports it
FALLBACK = "For accurate details, please contact us directly and we'll be happy to help."


def _normalize(text: str) -> str:
    t = (text or "").lower().strip()
    if not t:
        return ""
    t = re.sub(r"\bur\b", "your", t)
    t = re.sub(r"\bu\b", "you", t)
    t = re.sub(r"[^a-z0-9\s\$\?]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def is_capability_question(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False
    if re.search(r"\b(can|could)\s+(you|u|ya)\b", t):
        return True
    if re.search(r"\bdo\s+(you|u|ya)\b", t):
        return True
    if "do you offer" in t or "are you able to" in t:
        return True
    return False


def is_logistics_question(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False

    logistics_markers = [
        "water and power", "need water", "need power", "water", "power", "electricity",
        "power point", "powerpoint",
        "are you mobile", "mobile", "come to me", "come to my", "do you come", "can you come",
        "do you travel", "travel to",
        "parking", "keys", "key", "access", "gate code", "lockbox",
    ]
    return any(m in t for m in logistics_markers)


_DOMAINS = [
    ("pricing", [
        r"\bprice\b", r"\bpricing\b", r"\bcost\b", r"\bhow much\b", r"\bquote\b", r"\bestimate\b",
        r"\$", r"\baud\b", r"\bdollars?\b",
    ]),
    ("time", [
        r"\bhow long\b", r"\bduration\b", r"\bminutes?\b", r"\bmins?\b", r"\bhours?\b", r"\bhrs?\b", r"\bdays?\b",
        r"\barrival\b", r"\btime window\b", r"\bwindow\b",
    ]),
    ("payment", [
        r"\bpay\b", r"\bpayment\b", r"\binvoices?\b", r"\breceipt\b",
        r"\bbank transfer\b", r"\btransfer\b", r"\bcard\b", r"\beft\b", r"\bcash\b",
    ]),
    ("travel", [
        r"\btravel\b", r"\bdistance\b", r"\bkm\b", r"\bsurcharge\b", r"\boutside\b", r"\btoll\b", r"\bparking\b",
    ]),
    ("policy", [
        r"\bcancel\b", r"\bcancellation\b", r"\brefund\b", r"\breschedule\b",
        r"\bavailability\b", r"\bbook\b", r"\bbooking\b", r"\blate cancellation\b", r"\blate fee\b",
    ]),
    ("service_area", [
        r"\bservice area\b", r"\bservice areas\b", r"\bcoverage\b",
        r"\bsuburb\b", r"\bsuburbs\b",
        r"\bwhere do you\b", r"\bwhere do you service\b", r"\bdo you service\b",
        r"\bcover\b", r"\bcovered\b", r"\bcovering\b",
        r"\bradius\b", r"\bwithin\b", r"\bkm\b",
        r"\bnorthside\b", r"\bsouthside\b", r"\bcbd\b",
        r"\bbrisbane\b",
    ]),
    ("other", [
        r"\bsupply\b", r"\bsupplies\b", r"\bcleaning supplies\b", r"\bequipment\b", r"\bproducts?\b", r"\bvacuum\b",
        r"\bbring\b", r"\bown products\b", r"\bgear\b",
        r"\binsurance\b", r"\binsured\b", r"\bpublic liability\b",
        r"\bpets?\b", r"\bdog\b", r"\bcat\b",
    ]),
]


def classify_fact_domain(text: str) -> str:
    t = _normalize(text)
    if not t:
        return "none"

    # Don't route obvious general knowledge into business
    if re.search(r"\b(why|explain|what is|what's|how does|define)\b", t):
        return "none"

    for domain, pats in _DOMAINS:
        for p in pats:
            if re.search(p, t):
                return domain

    if is_capability_question(t) or is_logistics_question(t):
        return "capability"

    return "none"


def is_fact_question(text: str) -> bool:
    return classify_fact_domain(text) != "none"


_GENERAL_BLOCK_PATTERNS = [
    r"\$", r"\baud\b",
    r"\b(starting at|from\s+\$|we charge|charges?)\b",
    r"\b(price|pricing|cost|quote|estimate|fee)\b",
    r"\b\d+(?:\.\d+)?\s*(min|mins|minutes|hour|hours|day|days)\b",
    r"\btravel fee\b",
    r"\b(cancellation|refund)\b",
    r"\b(book|booking|availability|invoice|payment|pay|card|bank transfer|deposit)\b",
    r"\b(contact us|message us|call us|email us|reach out)\b",
]


def violates_general_safety(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return True
    return any(re.search(p, t) for p in _GENERAL_BLOCK_PATTERNS)