import re

# EXACT fallback sentence (ASCII only)
FALLBACK = "For accurate details, please contact us directly and we'll be happy to help."


# Domain patterns (case-insensitive). Order matters.
_DOMAINS: list[tuple[str, list[str]]] = [
    ("pricing", [
        r"\bprice\b", r"\bcost\b", r"\bfee\b", r"\bcharge\b", r"\bhow much\b", r"\$", r"\baud\b", r"\bdollars?\b",
        r"\bquote\b",
    ]),
    ("time", [
        r"\bhow long\b", r"\bduration\b", r"\bminutes?\b", r"\bmins?\b", r"\bhours?\b", r"\bhrs?\b", r"\bdays?\b",
        r"\barrival\b", r"\btime window\b", r"\bwindow\b",
    ]),
    ("inclusions", [
        r"\binclude\b", r"\bincluded\b", r"\bwhat('?s| is) in\b", r"\binclusions?\b", r"\bchecklist\b",
        r"\bstandard clean\b", r"\bdeep clean\b",
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

    # bond / vacate / end-of-lease routing
    ("clean_type", [
        r"\bbond\b",
        r"\bbond clean\b", r"\bbond cleans\b", r"\bbond cleaning\b",
        r"\bvacate\b", r"\bvacate clean\b", r"\bvacate cleans\b", r"\bvacate cleaning\b",
        r"\bend of lease\b", r"\bend-of-lease\b",
        r"\bend of tenancy\b", r"\bmove(?:ing)? out\b",
        r"\bexit clean\b", r"\blease clean\b", r"\bvacate service\b", r"\bvacate services\b",
        r"\bend of lease clean\b", r"\bvacate clean(?:ing)? service\b",
    ]),

    # service area routing
    ("service_area", [
        r"\bservice area\b", r"\bservice areas\b", r"\bcoverage\b",
        r"\bsuburb\b", r"\bsuburbs\b",
        r"\bwhere do you\b", r"\bwhere do you service\b", r"\bdo you service\b",
        r"\bcover\b", r"\bcovered\b", r"\bcovering\b",
        r"\bradius\b", r"\bwithin\b", r"\bkm\b",
        r"\bnorthside\b", r"\bsouthside\b", r"\bcbd\b",
        r"\bbrisbane\b", r"\bbris\b",
    ]),

    # operational / capability / “do you…” questions (these must NOT be answered by general chat)
    ("other", [
        # supplies intent (messy slang)
        r"\bsupply\b", r"\bsupplying\b", r"\bneed to supply\b", r"\bgotta supply\b",
        r"\bsupplies\b", r"\bcleaning supplies\b", r"\bequipment\b", r"\bproducts?\b", r"\bvacuum\b",
        r"\bbring\b", r"\bown products\b",

        # generic capability phrasing
        r"\bdo you (?:clean|offer|provide|handle|polish|wash|service|bring)\b",
        r"\bcan you (?:clean|do|handle|polish|wash|service|bring)\b",

        # common add-ons / services keywords
        r"\boven\b", r"\bfridge\b", r"\bwindows?\b", r"\bwindow cleaning\b",
        r"\blaundry\b", r"\blinen\b", r"\bbeds?\b",
        r"\bpets?\b", r"\bdog\b", r"\bcat\b",
        r"\binsurance\b", r"\binsured\b", r"\bpublic liability\b",
    ]),
]


# General-chat safety (LLM must not leak facts)
_GENERAL_BLOCK_PATTERNS = [
    r"\$", r"\baud\b",
    r"\d+\s*(min|mins|minutes|hour|hours|day|days)",
    r"\bwe charge\b", r"\bcharges?\b",
    r"\bprice\b", r"\bcost\b", r"\bfee\b",
    r"\bincludes?\b",
    r"\btravel fee\b",
    r"\bcancellation\b", r"\brefund\b",
]


def _normalize(text: str) -> str:
    t = (text or "").lower().strip()
    if not t:
        return ""
    # quick slang normalizer (keeps it deterministic)
    t = re.sub(r"\bur\b", "your", t)
    t = re.sub(r"\bu\b", "you", t)
    t = re.sub(r"[^a-z0-9\s\$\?]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def classify_fact_domain(text: str) -> str:
    t = _normalize(text)
    if not t:
        return "none"

    for domain, pats in _DOMAINS:
        for p in pats:
            if re.search(p, t):
                return domain
    return "none"


def is_fact_question(text: str) -> bool:
    return classify_fact_domain(text) != "none"


def violates_general_safety(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False
    return any(re.search(p, t) for p in _GENERAL_BLOCK_PATTERNS)
