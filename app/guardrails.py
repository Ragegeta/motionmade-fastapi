import re

# EXACT fallback sentence (ASCII only)
FALLBACK = "For accurate details, please contact us directly and we'll be happy to help."


# Domain patterns (case-insensitive). Order matters.
_DOMAINS: list[tuple[str, list[str]]] = [
    ("pricing", [
        r"\bprice\b", r"\bcost\b", r"\bfee\b", r"\bcharge\b", r"\bhow much\b", r"\$", r"\baud\b",
    ]),
    ("time", [
        r"\bhow long\b", r"\bduration\b", r"\bminutes?\b", r"\bhours?\b", r"\bdays?\b",
    ]),
    ("inclusions", [
        r"\binclude\b", r"\bincluded\b", r"\bwhat('?s| is) in\b", r"\binclusions?\b",
    ]),
    ("payment", [
        r"\bpay\b", r"\bpayment\b", r"\binvoice\b", r"\breceipt\b", r"\bbank transfer\b", r"\bcard\b",
    ]),
    ("travel", [
        r"\btravel\b", r"\bdistance\b", r"\bkm\b", r"\bsurcharge\b",
    ]),
    ("policy", [
        r"\bcancel\b", r"\bcancellation\b", r"\brefund\b", r"\breschedule\b",
        r"\bavailability\b", r"\bbook\b", r"\bbooking\b",
    ]),

    # NEW: bond / vacate / end-of-lease routing (so these enter fact branch + retrieval)
    ("clean_type", [
        r"\bbond\b",
        r"\bbond clean\b", r"\bbond cleans\b", r"\bbond cleaning\b",
        r"\bvacate\b", r"\bvacate clean\b", r"\bvacate cleans\b",
        r"\bend of lease\b", r"\bend-of-lease\b",
        r"\bend of tenancy\b", r"\bmove(?:ing)? out\b",
        r"\bexit clean\b", r"\blease clean\b",
    ]),

    # service area routing
    ("service_area", [
        r"\bservice area\b", r"\bservice areas\b", r"\bcoverage\b",
        r"\barea\b", r"\bareas\b",
        r"\bsuburb\b", r"\bsuburbs\b",
        r"\blocation\b", r"\blocations\b",
        r"\bwhere do you\b",
        r"\bwhere do you service\b",
        r"\bdo you service\b",
        r"\bradius\b", r"\bwithin\b", r"\bkm\b",
        r"\bnorthside\b", r"\bsouthside\b", r"\bcbd\b",
    ]),

    # service capability questions (e.g. "Do you polish marble benchtops?")
    ("other", [
        r"\bdo you (?:clean|offer|provide|handle|polish|wash|service)\b",
        r"\bcan you (?:clean|do|handle|polish|wash|service)\b",
        r"\bwindow cleaning\b", r"\bclean windows?\b", r"\bwindows?\b",
        r"\bfridge cleaning\b", r"\bfridge\b",
        r"\bpets?\b", r"\bdog\b", r"\bcat\b",
        r"\bsupplies?\b", r"\bequipment\b", r"\bproducts?\b", r"\bbring\b",
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
    if not text:
        return "none"
    t = text.lower()

    # Hard guarantees for supplies / equipment / products questions
    if "supplies" in t or "equipment" in t or "cleaning products" in t or "products" in t:
        return "other"

    for domain, pats in _DOMAINS:
        for p in pats:
            if re.search(p, t):
                return domain
    return "none"


def is_fact_question(text: str) -> bool:
    return classify_fact_domain(text) != "none"


def violates_general_safety(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(re.search(p, t) for p in _GENERAL_BLOCK_PATTERNS)
