import re

# EXACT fallback sentence (ASCII only)
FALLBACK = "For accurate details, please contact us directly and we'll be happy to help."

# Deterministic business-fact patterns
_FACT_PATTERNS = [
    
    r"\bwindows?\b", r"\bwindow cleaning\b", r"\bclean windows?\b",
    r"\bfridge\b", r"\bfridge cleaning\b",
    r"\bpets?\b", r"\bdog\b", r"\bcat\b",
r"\bprice\b",
    r"\bcost\b",
    r"\bfee\b",
    r"\bcharge\b",
    r"\bhow much\b",
    r"\$",
    r"\baud\b",

    r"\bhow long\b",
    r"\bduration\b",
    r"\bminutes?\b",
    r"\bhours?\b",

    r"\binclude\b",
    r"\bincluded\b",
    r"\bwhat('?s| is) in\b",
    r"\binclusions?\b",

    r"\bpay\b",
    r"\bpayment\b",
    r"\binvoice\b",
    r"\breceipt\b",
    r"\bbank transfer\b",
    r"\bcard\b",

    r"\btravel\b",
    r"\bdistance\b",
    r"\bkm\b",
    r"\bsurcharge\b",

    r"\bcancel\b",
    r"\bcancellation\b",
    r"\brefund\b",
    r"\breschedule\b",

    r"\bavailability\b",
    r"\bbook\b",
    r"\bbooking\b",
    r"\bschedule\b",

    # supplies / equipment
    r"\bsupplies?\b",
    r"\bequipment\b",
    r"\bproducts?\b",
    r"\bcleaning products?\b",
    r"\bbring\b",
]

# General-chat safety (LLM must not leak facts)
_GENERAL_BLOCK_PATTERNS = [
    r"\$",
    r"\baud\b",
    r"\d+\s*(min|mins|minutes|hour|hours)",
    r"\bwe charge\b",
    r"\bcharges?\b",
    r"\bprice\b",
    r"\bcost\b",
    r"\bfee\b",
    r"\bincludes?\b",
    r"\btravel fee\b",
    r"\bcancellation\b",
    r"\brefund\b",
]

def is_fact_question(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(re.search(p, t) for p in _FACT_PATTERNS)

def violates_general_safety(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(re.search(p, t) for p in _GENERAL_BLOCK_PATTERNS)