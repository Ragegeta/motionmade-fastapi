import re

# EXACT fallback sentence (ASCII only)
FALLBACK = "For accurate details, please contact us directly and we'll be happy to help."


def _normalize(text: str) -> str:
    t = (text or "").lower().strip()
    if not t:
        return ""

    # slang normalizer (keep deterministic)
    t = re.sub(r"\bur\b", "your", t)
    t = re.sub(r"\bu\b", "you", t)
    t = re.sub(r"\bya\b", "you", t)
    t = re.sub(r"\byeh\b", "yes", t)
    t = re.sub(r"\bn\b", "and", t)

    # common abbrevs
    t = re.sub(r"\bbrisb\b", "brisbane", t)
    t = re.sub(r"\bbris\b", "brisbane", t)

    # keep $, ? for “how much?” / pricing-ish signals
    t = re.sub(r"[^a-z0-9\s\$\?]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# -----------------------------
# Capability detection (universal)
# -----------------------------
_CAPABILITY_PATTERNS = [
    r"\bcan\s+(you|u)\b",
    r"\bcould\s+(you|u)\b",
    r"\bdo\s+(you|u)\b",
    r"\bdo\s+you\s+do\b",
    r"\bdo\s+you\s+offer\b",
    r"\bare\s+you\s+able\s+to\b",
    r"\bable\s+to\b",
    r"\bdo\s+you\s+provide\b",
    r"\bcan\s+you\s+fix\b",
    r"\bdo\s+you\s+fix\b",
    r"\bcan\s+you\s+repair\b",
    r"\bdo\s+you\s+repair\b",
    r"\bcan\s+you\s+install\b",
    r"\bdo\s+you\s+install\b",
]


def is_capability_question(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False

    # Exclusions: general knowledge phrasing
    if re.search(r"\b(why|explain|what is|what's|how does|define)\b", t):
        return False

    return any(re.search(p, t) for p in _CAPABILITY_PATTERNS)


# -----------------------------
# Logistics / ops detection (universal)
# -----------------------------
_LOGISTICS_KEYWORDS = [
    # water/power
    "water", "power", "electricity", "power point", "powerpoint",
    # mobile / travel
    "mobile", "come to me", "come to my", "do you come", "can you come", "do you travel", "travel to",
    # access / keys / parking
    "parking", "visitor spot", "keys", "key", "access", "gate code", "lockbox",
]


def is_logistics_question(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False

    # make water/power require both signals, to reduce false positives
    if ("water" in t) and ("power" in t or "electricity" in t or "power point" in t or "powerpoint" in t):
        return True

    if any(k in t for k in [
        "are you mobile", "do you come", "come to me", "come to my", "do you travel", "travel to"
    ]):
        return True

    if any(k in t for k in ["parking", "visitor spot", "keys", "key", "access", "gate code", "lockbox"]):
        return True

    return False


# -----------------------------
# General-response safety check
# (blocks business specifics leaking into general chat)
# -----------------------------
_GENERAL_BLOCK_PATTERNS = [
    r"\$\s*\d",                         # $149
    r"\b\d+\s*(aud|dollars?)\b",        # 149 dollars
    r"\bstarts?\s+at\b",
    r"\bfrom\s+\$\s*\d",
    r"\b(price|pricing|cost|fee|deposit|invoice|callout)\b",
    r"\b(hours?|hrs?|minutes?|mins?|days?)\b",
]


def violates_general_safety(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False
    return any(re.search(p, t) for p in _GENERAL_BLOCK_PATTERNS)


# -----------------------------
# Legacy “fact gate” domain classification
# (used for headers + fallback decisions, NOT to decide retrieval)
# -----------------------------
def classify_fact_domain(text: str) -> str:
    t = _normalize(text)
    if not t:
        return "none"

    # hard universal business signals
    if is_capability_question(t):
        return "capability"
    if is_logistics_question(t):
        return "other"

    # existing stable domains
    if re.search(r"\b(\$|price|pricing|cost|how much|quote|starts at|from)\b", t):
        return "pricing"
    if re.search(r"\b(brisbane|suburb|service area|do you cover|cover.*suburb|travel fee)\b", t):
        return "service_area"
    if re.search(r"\b(pay|payment|card|bank transfer|invoice)\b", t):
        return "payment"
    if re.search(r"\b(supplies|equipment|bring.*vacuum|bring.*supplies|do i provide)\b", t):
        return "supplies"

    return "none"