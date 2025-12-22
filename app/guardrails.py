import re

# EXACT fallback sentence (ASCII only)
FALLBACK = "For accurate details, please contact us directly and we'll be happy to help."


def _normalize(text: str) -> str:
    t = (text or "").lower().strip()
    if not t:
        return ""
    # small deterministic slang normalizer
    t = re.sub(r"\bur\b", "your", t)
    t = re.sub(r"\bu\b", "you", t)
    t = re.sub(r"[^a-z0-9\s\$\?]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ---- Capability gating (MUST route to fact branch) ----
# Rule: ability/offer phrase + service-ish noun, in same message.
# IMPORTANT: include slang forms ("can ya", "u guys do", etc.)
_CAP_VERBS = [
    r"\bcan you\b",
    r"\bcan u\b",
    r"\bcan ya\b",
    r"\bdo you\b",
    r"\bdo u\b",
    r"\bdo ya\b",
    r"\byou guys do\b",
    r"\byou guys\b.*\bdo\b",
    r"\bu guys do\b",
    r"\bu guys\b.*\bdo\b",
    r"\bare you able to\b",
    r"\bable to\b",
    r"\bprovide\b",
    r"\boffer\b",
    r"\bservice\b",
    r"\bhandle\b",
]

# nouns/phrases that indicate "service capability"
_CAP_NOUNS = [
    r"\bclean\b", r"\bcleaning\b",
    r"\bsteam\b", r"\bsteaming\b",
    r"\bcarpet\b", r"\bcarpets\b",
    r"\bcouch\b", r"\bcouches\b", r"\bsofa\b", r"\bupholstery\b",
    r"\boven\b", r"\bfridge\b",
    r"\bwindow\b", r"\bwindows\b",
    r"\bbathroom\b", r"\bbathrooms\b",
    r"\bbond\b", r"\bvacate\b", r"\bend of lease\b", r"\bend-of-lease\b",
    r"\bdeep clean\b", r"\bstandard clean\b",
    r"\bmop\b", r"\bvacuum\b",
    # pressure/power washing slang + contexts
    r"\bpressure wash\b", r"\bpressure washing\b", r"\bpressure-washing\b",
    r"\bpower wash\b", r"\bpower washing\b", r"\bpower-washing\b",
    r"\bdriveway\b",
    # common “do you do X?” service traps
    r"\bmould\b", r"\bmold\b", r"\bmould removal\b", r"\bmold removal\b",
    r"\btiles?\b", r"\bgrout\b", r"\btiles and grout\b",
    r"\bbuilder'?s\b", r"\bbuilders\b", r"\bbuilder'?s clean\b", r"\bbuilders clean\b", r"\bpost construction\b",
    r"\bblinds\b",
    r"\bgarage\b",
]


def _is_capability_question(t: str) -> bool:
    if not t:
        return False
    if not any(re.search(p, t) for p in _CAP_VERBS):
        return False
    if not any(re.search(p, t) for p in _CAP_NOUNS):
        return False
    return True


# Domain patterns. Order matters.
_DOMAINS: list[tuple[str, list[str]]] = [
    ("pricing", [
        r"\bprice\b", r"\bcost\b", r"\bfee\b", r"\bcharge\b", r"\bhow much\b",
        r"\$", r"\baud\b", r"\bdollars?\b", r"\bquote\b",
    ]),
    ("time", [
        r"\bhow long\b", r"\bduration\b", r"\bminutes?\b", r"\bmins?\b",
        r"\bhours?\b", r"\bhrs?\b", r"\bdays?\b",
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
    ("clean_type", [
        r"\bbond\b",
        r"\bbond clean\b", r"\bbond cleans\b", r"\bbond cleaning\b",
        r"\bvacate\b", r"\bvacate clean\b", r"\bvacate cleans\b", r"\bvacate cleaning\b",
        r"\bend of lease\b", r"\bend-of-lease\b",
        r"\bend of tenancy\b", r"\bmove(?:ing)? out\b",
        r"\bexit clean\b", r"\blease clean\b",
        r"\bend of lease clean\b", r"\bvacate clean(?:ing)? service\b",
    ]),
    ("service_area", [
        r"\bservice area\b", r"\bservice areas\b", r"\bcoverage\b",
        r"\bsuburb\b", r"\bsuburbs\b",
        r"\bwhere do you\b", r"\bwhere do you service\b", r"\bdo you service\b",
        r"\bcover\b", r"\bcovered\b", r"\bcovering\b",
        r"\bradius\b", r"\bwithin\b", r"\bkm\b",
        r"\bnorthside\b", r"\bsouthside\b", r"\bcbd\b",
        r"\bbrisbane\b", r"\bbris\b",
    ]),
    ("other", [
        r"\bsupply\b", r"\bsupplying\b", r"\bneed to supply\b", r"\bgotta supply\b",
        r"\bsupplies\b", r"\bcleaning supplies\b", r"\bequipment\b", r"\bproducts?\b", r"\bvacuum\b",
        r"\bbring\b", r"\bown products\b",
        r"\binsurance\b", r"\binsured\b", r"\bpublic liability\b",
        r"\bpets?\b", r"\bdog\b", r"\bcat\b",
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


def classify_fact_domain(text: str) -> str:
    t = _normalize(text)
    if not t:
        return "none"

    # capability first (safety-first): prevents any "yes we do X" leaks
    if _is_capability_question(t):
        return "capability"

    # then specific domains
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
