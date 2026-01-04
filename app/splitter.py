import re

MAX_INTENTS = 3

SPLIT_PATTERNS = [
    r'\?\s*(?:and\s+)?also\s+',
    r'\?\s+(?:and\s+)?(?=[A-Za-z])',
    r'\s+also[:\s]+',
    r'\s+and\s+also\s+',
    r'\s*,\s*and\s+',
]


def split_intents(text: str) -> list:
    if not text:
        return []

    t = text.strip()

    parts = [t]
    for pattern in SPLIT_PATTERNS:
        new_parts = []
        for p in parts:
            splits = re.split(pattern, p, flags=re.IGNORECASE)
            new_parts.extend(splits)
        parts = new_parts

    cleaned = []
    for p in parts:
        p = p.strip().rstrip('?').strip()
        if len(p) >= 3:
            cleaned.append(p)

    seen = set()
    unique = []
    for p in cleaned:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return unique[:MAX_INTENTS]


