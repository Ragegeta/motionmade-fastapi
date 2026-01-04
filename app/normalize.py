import re
import unicodedata

SLANG_MAP = [
    (r'\bur\b', 'your'),
    (r'\bu\b', 'you'),
    (r'\bya\b', 'you'),
    (r'\byeh\b', 'yes'),
    (r'\bpls\b', 'please'),
    (r'\bthx\b', 'thanks'),
    (r'\bcoz\b', 'because'),
    (r'\bwat\b', 'what'),
    (r'\bhwo\b', 'how'),
    (r'\breckon\b', 'think'),
    (r'\barvo\b', 'afternoon'),
    (r'\bbrissy\b', 'brisbane'),
    (r'\bbris\b', 'brisbane'),
    (r"\bg'day\b", 'hello'),
    (r'\bmate\b', ''),
    (r'\b2\b', 'to'),
    (r'\b4\b', 'for'),
]

FLUFF_PREFIXES = [
    r'^hey\s+(quick\s+one|there|so)\s*[-\u2013\u2014:]?\s*',
    r'^just\s+wondering\s*[-\u2013\u2014,:]?\s*',
    r'^(so\s+)?basically\s*[-\u2013\u2014,:]?\s*',
    r'^hi\s+(there\s*)?[-\u2013\u2014!,:]?\s*',
    r'^sorry\s+to\s+bother\s+(you\s+)?but\s*',
    r'^okay\s+so\s+',
    r'^ok\s+so\s+',
    r'^quick\s+(question|q)\s*[-\u2013\u2014:]?\s*',
]

FLUFF_SUFFIXES = [
    r'\s*thanks?\s*(so\s+much)?[!.]*$',
    r'\s*thx[!.]*$',
    r'\s*cheers[!.]*$',
    r'\s*please\s+advise[!.]*$',
    r"\s*i'?m\s+flexible[^.]*[!.]*$",
    r'\s*just\s+tell\s+me[!.]*$',
]

CONTRACTIONS = [
    (r"\bwhat's\b", 'what is'),
    (r"\bwhat're\b", 'what are'),
    (r"\bhow's\b", 'how is'),
    (r"\bdon't\b", 'do not'),
    (r"\bdoesn't\b", 'does not'),
    (r"\bcan't\b", 'cannot'),
    (r"\bwon't\b", 'will not'),
    (r"\bi'm\b", 'i am'),
    (r"\byou're\b", 'you are'),
    (r"\bthey're\b", 'they are'),
    (r"\bwe're\b", 'we are'),
    (r"\bit's\b", 'it is'),
    (r"\bthat's\b", 'that is'),
    (r"\bthere's\b", 'there is'),
    (r"\bhere's\b", 'here is'),
    (r"\blet's\b", 'let us'),
    (r"\bi've\b", 'i have'),
    (r"\byou've\b", 'you have'),
    (r"\bwe've\b", 'we have'),
    (r"\bthey've\b", 'they have'),
    (r"\bi'd\b", 'i would'),
    (r"\byou'd\b", 'you would'),
    (r"\bhe'd\b", 'he would'),
    (r"\bshe'd\b", 'she would'),
    (r"\bwe'd\b", 'we would'),
    (r"\bthey'd\b", 'they would'),
    (r"\bi'll\b", 'i will'),
    (r"\byou'll\b", 'you will'),
    (r"\bhe'll\b", 'he will'),
    (r"\bshe'll\b", 'she will'),
    (r"\bwe'll\b", 'we will'),
    (r"\bthey'll\b", 'they will'),
]


def normalize_unicode(text: str) -> str:
    t = unicodedata.normalize('NFKC', text)
    t = t.replace('\u2018', "'").replace('\u2019', "'")
    t = t.replace('\u201c', '"').replace('\u201d', '"')
    t = t.replace('\u2013', '-').replace('\u2014', '-').replace('\u2212', '-')
    t = t.replace('\u2026', '...')
    t = t.replace('\u00a0', ' ')
    return t


def expand_slang(text: str) -> str:
    t = text
    for pattern, replacement in SLANG_MAP:
        t = re.sub(pattern, replacement, t, flags=re.IGNORECASE)
    return t


def expand_contractions(text: str) -> str:
    t = text
    for pattern, replacement in CONTRACTIONS:
        t = re.sub(pattern, replacement, t, flags=re.IGNORECASE)
    return t


def remove_fluff(text: str) -> str:
    t = text
    for pattern in FLUFF_PREFIXES:
        t = re.sub(pattern, '', t, flags=re.IGNORECASE)
    for pattern in FLUFF_SUFFIXES:
        t = re.sub(pattern, '', t, flags=re.IGNORECASE)
    return t.strip()


def normalize_whitespace(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def normalize_message(text: str) -> str:
    if not text:
        return ""
    t = text
    t = normalize_unicode(t)
    t = t.lower()
    t = expand_contractions(t)
    t = expand_slang(t)
    t = remove_fluff(t)
    t = normalize_whitespace(t)
    return t

