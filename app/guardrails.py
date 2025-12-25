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

    t = re.sub(r"[^a-z0-9\s\$\?]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ---- Capability gating (MUST route to fact branch) ----
# Rule: ability/offer phrase + service-ish noun, in same message.
_CAP_VERBS = [
    r"\bcan (you|u|ya)\b",
    r"\bcan ya\b",
    r"\bdo (you|u|ya)\b",
    r"\bdo you do\b",
    r"\bdo you offer\b",
    r"\bdo u offer\b",
    r"\bdo ya offer\b",
    r"\byou guys (do|offer|provide|service|handle)\b",
    r"\bu guys (do|offer|provide|service|handle)\b",
    r"\bare you able to\b",
    r"\bable to\b",
    r"\bprovide\b",
    r"\boffer\b",
    r"\bservice\b",
    r"\bhandle\b",
    r"\\b(can|could)\\s+(you|u)\\s+fix\\b",
    r"\\b(can|could)\\s+(you|u)\\s+install\\b",
    r"\\b(can|could)\\s+(you|u)\\s+repair\\b",
    r"\\bdo\\s+(you|u)\\s+fix\\b",
    r"\\bdo\\s+(you|u)\\s+install\\b",
    r"\\bdo\\s+(you|u)\\s+repair\\b",
    r"\\bdo\\s+(you|u)\\s+offer\\b",
    r"\\boffer\\s+\\w+\\b",
]

_CAP_NOUNS = [
    # generic cleaning/service language
    r"\bclean\b", r"\bcleaning\b", r"\bdeep clean\b", r"\bstandard clean\b",
    r"\bvacc?uum\b", r"\bmop\b",

    # carpets / upholstery
    r"\bsteam\b", r"\bsteam clean\b", r"\bcarpet\b", r"\bcarpets\b",
    r"\bcouch\b", r"\bcouches\b", r"\bsofa\b", r"\bupholstery\b",

    # add-ons / areas people ask about
    r"\boven\b", r"\bfridge\b", r"\bwindow\b", r"\bwindows\b",
    r"\bblind\b", r"\bblinds\b",
    r"\bgarage\b", r"\bdriveway\b",

    # end-of-lease language
    r"\bbond\b", r"\bvacate\b", r"\bend of lease\b", r"\bend-of-lease\b",

    # pressure / power washing
    r"\bpressure wash\b", r"\bpressure washing\b", r"\bpressure-washing\b",
    r"\bpower wash\b", r"\bpower washing\b", r"\bpower-washing\b",

    # other common “do you do X” services people ask cleaners about
    r"\bmould\b", r"\bmold\b", r"\bmould removal\b", r"\bmold removal\b", r"\bremoval\b",
    r"\btiles?\b", r"\bgrout\b", r"\btiles and grout\b",
    r"\bbuilder\b", r"\bbuilders\b", r"\bbuilder'?s\b", r"\bbuilders clean\b", r"\bbuilders cleans\b",
    r"\bpest\b", r"\bpest control\b",
]


def _is_capability_question(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False

    # Exclusions: user asking for an explanation (general knowledge)
    if re.search(r"\b(why|explain|what is|what's|how does|define)\b", t):
        return False

    # Safety-first: any "can you / do you / do u / are you able to / do you offer" style capability question
    return any(re.search(p, t) for p in _CAP_VERBS)

def violates_general_safety(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False
    return any(re.search(p, t) for p in _GENERAL_BLOCK_PATTERNS)

# REPLICA_PATCH_V1
