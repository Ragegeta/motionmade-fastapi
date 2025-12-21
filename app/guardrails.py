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
        r"\barrival window\b", r"\btime window\b",
    ]),
    ("inclusions", [
        r"\binclude\b", r"\bincluded\b", r"\bwhat('?s| is) in\b", r"\binclusions?\b",
        r"\bchecklist\b",
    ]),
    ("payment", [
        r"\bpay\b", r"\bpayment\b", r"\binvoice\b", r"\breceipt\b", r"\bbank transfer\b", r"\bcard\b",
    ]),
    ("travel", [
        r"\btravel\b", r"\bdistance\b", r"\bkm\b", r"\bsurcharge\b", r"\btravel fee\b",
    ]),
    ("policy", [
        r"\bcancel\b", r"\bcancellation\b", r"\brefund\b", r"\breschedule\b",
        r"\bavailability\b", r"\bbook\b", r"\bbooking\b",
        r"\blate cancellation\b",
    ]),

    # Bond / vacate / end-of-lease / moving out
    ("clean_type", [
        r"\bbond\b",
        r"\bbond clean\b", r"\bbond cleans\b", r"\bbond cleaning\b",
        r"\bvacate\b", r"\bvacate clean\b", r"\bvacate cleans\b",
        r"\bend of lease\b", r"\bend-of-lease\b",
        r"\bend of tenancy\b",
        r"\bmove(?:ing)? out\b",
        r"\bexit clean\b", r"\blease clean\b",
    ]),

    # Service area / coverage
    ("service_area", [
        r"\bservice area\b", r"\bservice areas\b", r"\bcoverage\b",
        r"\barea\b", r"\bareas\b",
        r"\bsuburb\b", r"\bsuburbs\b",
        r"\blocation\b", r"\blocations\b",
        r"\bwhere do you\b",
        r"\bwhere do you service\b",
        r"\bdo you service\b",
        r"\bdo u (?:service|clean)\b",
        r"\bcover\b", r"\bcoverage\b",
        r"\bradius\b", r"\bwithin\b", r"\bkm\b",
        r"\bnorthside\b", r"\bsouthside\b", r"\bcbd\b",
        r"\bbrisbane\b",
    ]),

    # Parking / access
    ("parking", [
        r"\bparking\b", r"\bpaid parking\b", r"\bvisitor (?:spot|parking)\b",
        r"\baccess\b", r"\bbuilding access\b", r"\bgate code\b", r"\bkey\b", r"\bkeys\b",
        r"\bintercom\b", r"\blift\b",
    ]),

    # Linen / beds
    ("linen", [
        r"\blinen\b", r"\bsheets?\b", r"\btowels?\b",
        r"\bchange (?:the )?sheets?\b", r"\bmake (?:the )?beds?\b", r"\bbeds?\b",
    ]),

    # Insurance
    ("insurance", [
        r"\binsured\b", r"\binsurance\b", r"\bpublic liability\b", r"\bliability\b",
    ]),

    # Service capability / “do you do X”
    ("other", [
        r"\bdo you (?:clean|offer|provide|handle|polish|wash|service)\b",
        r"\bcan you (?:clean|do|handle|polish|wash|service)\b",
        r"\bwindow cleaning\b", r"\bclean windows?\b", r"\bwindows?\b",
        r"\bfridge cleaning\b", r"\bfridge\b",
        r"\bpets?\b", r"\bdog\b", r"\bcat\b",
        r"\bsupplies?\b", r"\bequipment\b", r"\bproducts?\b", r"\bbring\b", r"\bvacu(?:u)?m\b",
        # Route these into fact branch so they safely FALLBACK (no hallucinated service claims)
        r"\bcarpet\b", r"\bsteam clean\b", r"\bsteam cleaning\b",
        r"\bpest control\b",
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
    if (
        "supplies" in t
        or "equipment" in t
        or "cleaning products" in t
        or "products" in t
        or "vacuum" in t
        or "vacu" in t
    ):
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
