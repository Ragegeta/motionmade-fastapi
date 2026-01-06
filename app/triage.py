import re
import unicodedata

CLARIFY_RESPONSE = "Could you please rephrase your question? I want to make sure I understand what you're asking."


def _count_meaningful_chars(text: str) -> int:
    return sum(1 for c in text if c.isalnum())


def _is_emoji_only(text: str) -> bool:
    stripped = re.sub(r'[\s\u200b-\u200f\u2028-\u202f]', '', text or '')
    if not stripped:
        return True
    for c in stripped:
        cat = unicodedata.category(c)
        if cat.startswith('L') or cat.startswith('N'):
            return False
    return True


def triage_input(text: str) -> tuple:
    """
    Returns: (result: str, should_continue: bool)
    - ("pass", True) -> continue processing
    - ("clarify", False) -> return clarify response immediately
    """
    if not text:
        return ("clarify", False)

    t = text.strip()

    if not t:
        return ("clarify", False)

    if _count_meaningful_chars(t) < 3:
        return ("clarify", False)

    if _is_emoji_only(t):
        return ("clarify", False)

    # Gibberish: same char repeated
    if re.match(r'^([a-zA-Z])\1{5,}$', t):
        return ("clarify", False)

    # Random keyboard mash
    if re.match(r'^[a-z]{6,}$', t.lower()) and len(set(t.lower())) < 4:
        return ("clarify", False)

    # Repeated words only: "test test test"
    words = t.lower().split()
    if len(words) >= 3 and len(set(words)) == 1:
        return ("clarify", False)

    # Punctuation only
    if re.match(r'^[\s\.\?\!\,\;\:\-\_\=\+\*\&\^\%\$\#\@\!\~\`]+$', t):
        return ("clarify", False)

    return ("pass", True)



