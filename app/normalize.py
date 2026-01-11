import re
import unicodedata

SLANG_MAP = [
    # === CRITICAL: Single-letter shortcuts (must be first, word-boundary) ===
    (r'\br\b', 'are'),           # "r u" -> "are you"
    (r'\bu\b', 'you'),           # "u" -> "you"
    (r'\by\b', 'why'),           # "y" at word boundary -> "why" (context: "y not")
    (r'\bc\b', 'see'),           # "c u" -> "see you"
    (r'\bn\b', 'and'),           # "fish n chips" -> "fish and chips"
    (r'\bk\b', 'okay'),          # "k" -> "okay"
    (r'\bm\b', 'am'),            # "i m" -> "i am" (rare but happens)
    
    # === Two-letter shortcuts ===
    (r'\bur\b', 'your'),
    (r'\byr\b', 'your'),
    (r'\bya\b', 'you'),
    (r'\bda\b', 'the'),
    (r'\bma\b', 'my'),
    (r'\bim\b', 'i am'),
    (r'\biv\b', 'i have'),
    
    # Common words
    (r'\bpls\b', 'please'),
    (r'\bplz\b', 'please'),
    (r'\bthx\b', 'thanks'),
    (r'\bty\b', 'thank you'),
    (r'\bcoz\b', 'because'),
    (r'\bcuz\b', 'because'),
    (r'\bcos\b', 'because'),
    (r'\bbc\b', 'because'),
    (r'\btho\b', 'though'),
    (r'\bthru\b', 'through'),
    (r'\bw/\b', 'with'),
    (r'\bw/o\b', 'without'),
    
    # Questions
    (r'\bwat\b', 'what'),
    (r'\bwut\b', 'what'),
    (r'\bhwo\b', 'how'),
    (r'\bhw\b', 'how'),          # "hw much" -> "how much"
    (r'\bwhr\b', 'where'),
    (r'\bwen\b', 'when'),
    (r'\bcn\b', 'can'),          # "cn u" -> "can you"
    
    # Contractions/shortcuts
    (r'\bgonna\b', 'going to'),
    (r'\bwanna\b', 'want to'),
    (r'\bgotta\b', 'got to'),
    (r'\bkinda\b', 'kind of'),
    (r'\bsorta\b', 'sort of'),
    (r'\bdunno\b', 'do not know'),
    (r'\blemme\b', 'let me'),
    (r'\bgimme\b', 'give me'),
    
    # Australian slang
    (r'\breckon\b', 'think'),
    (r'\barvo\b', 'afternoon'),
    (r'\bbrekkie\b', 'breakfast'),
    (r'\bbrissy\b', 'brisbane'),
    (r'\bbris\b', 'brisbane'),
    (r'\bmelb\b', 'melbourne'),
    (r'\bsyd\b', 'sydney'),
    (r"\bg'day\b", 'hello'),
    (r'\bgday\b', 'hello'),
    (r'\bmate\b', ''),
    (r'\bno worries\b', 'okay'),
    (r'\bheaps\b', 'very'),
    
    # Numbers as words
    (r'\b2\b', 'to'),
    (r'\b4\b', 'for'),
    (r'\b2day\b', 'today'),
    (r'\b2moro\b', 'tomorrow'),
    (r'\b2nite\b', 'tonight'),
    (r'\bb4\b', 'before'),
    
    # Common misspellings
    (r'\bprice?s\b', 'prices'),
    (r'\bpriec\b', 'price'),
    (r'\bpirce\b', 'price'),
    (r'\bavail\b', 'available'),
    (r'\bavialable\b', 'available'),
    (r'\bclening\b', 'cleaning'),
    (r'\bcleaing\b', 'cleaning'),
    (r'\bservcie\b', 'service'),
    (r'\bsrevice\b', 'service'),
    
    # Electrical/technical typos
    (r'\bpwr\b', 'power'),           # "pwr out" -> "power out"
    (r'\bsaftey\b', 'safety'),       # "saftey switch" -> "safety switch"
    (r'\bswich\b', 'switch'),        # "swich" -> "switch"
    (r'\bswitchbord\b', 'switchboard'),  # "switchbord" -> "switchboard"
    (r'\blicenced\b', 'licensed'),   # "licenced" -> "licensed"
    (r'\bgoin\b', 'going'),          # "goin off" -> "going off"
    (r'\bbeepin\b', 'beeping'),      # "beepin" -> "beeping"
    (r'\bflickring\b', 'flickering'),  # "flickring" -> "flickering"
    (r'\bplumbr\b', 'plumber'),      # "plumbr" -> "plumber"
    (r'\bpanls\b', 'panels'),        # "solar panls" -> "solar panels"
    (r'\baircon\b', 'air con'),      # "aircon" -> "air con" (normalize to space-separated form)
]

FLUFF_PREFIXES = [
    r'^hey\s+(quick\s+one|there|so)\s*[-–—:]?\s*',
    r'^just\s+wondering\s*[-–—,:]?\s*',
    r'^(so\s+)?basically\s*[-–—,:]?\s*',
    r'^hi\s+(there\s*)?[-–—!,:]?\s*',
    r'^hello\s*[-–—!,:]?\s*',
    r'^sorry\s+to\s+bother\s+(you\s+)?but\s*',
    r'^okay\s+so\s+',
    r'^ok\s+so\s+',
    r'^quick\s+(question|q)\s*[-–—:]?\s*',
    r'^i\s+was\s+(just\s+)?wondering\s+(if\s+)?\s*',
    r'^would\s+it\s+be\s+possible\s+to\s+',
    r'^could\s+you\s+(please\s+)?tell\s+me\s+',
    r'^can\s+you\s+(please\s+)?tell\s+me\s+',
    r'^i\s+want(ed)?\s+to\s+(know|ask)\s+',
    r'^i\s+need\s+to\s+(know|ask)\s+',
    r"^g'?day\s*(mate\s*)?\s*[-–—,:]?\s*",
    r'^yo\s+',
    r'^oi\s+',
]

FLUFF_SUFFIXES = [
    r'\s*thanks?\s*(so\s+much)?[!.]*$',
    r'\s*thx[!.]*$',
    r'\s*ty[!.]*$',
    r'\s*cheers[!.]*$',
    r'\s*ta[!.]*$',
    r'\s*please\s+advise[!.]*$',
    r"\s*i'?m\s+flexible[^.]*[!.]*$",
    r'\s*just\s+(let\s+me\s+know|tell\s+me)[!.]*$',
    r'\s*if\s+poss(ible)?[!.]*$',
    r'\s*when\s+you\s+(can|get\s+a\s+chance)[!.]*$',
    r'\s*no\s+rush[!.]*$',
    r'\s*no\s+worries\s+if\s+not[!.]*$',
    r'\s*appreciate\s+it[!.]*$',
    r'\s*\?\?+$',
    r'\s*!+$',
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


def extract_core_question(text: str) -> str:
    """
    Extract the core question from verbose/polite phrasing.
    Examples:
        "could you tell me your prices" → "your prices"
        "i was wondering if you have availability" → "do you have availability"
        "would it be possible to book" → "book"
    """
    t = text.strip().lower()
    
    # Patterns that wrap the actual question
    WRAPPER_PATTERNS = [
        # "could you tell me X" → "X"
        (r'^could\s+you\s+(please\s+)?tell\s+me\s+(.+)$', r'\2'),
        # "can you tell me X" → "X"
        (r'^can\s+you\s+(please\s+)?tell\s+me\s+(.+)$', r'\2'),
        # "i want to know X" → "X"
        (r'^i\s+want(ed)?\s+to\s+know\s+(.+)$', r'\2'),
        # "i need to know X" → "X"
        (r'^i\s+need\s+to\s+know\s+(.+)$', r'\2'),
        # "would like to know X" → "X"
        (r'^(i\s+)?would\s+like\s+to\s+know\s+(.+)$', r'\2'),
        # "wondering if you X" → "do you X"
        (r'^(i\s+was\s+)?(just\s+)?wondering\s+if\s+you\s+(.+)$', r'do you \3'),
        # "wondering about X" → "X"
        (r'^(i\s+was\s+)?(just\s+)?wondering\s+about\s+(.+)$', r'\3'),
        # "would it be possible to X" → "can you X"
        (r'^would\s+it\s+be\s+possible\s+to\s+(.+)$', r'can you \1'),
        # "is it possible to X" → "can you X"
        (r'^is\s+it\s+possible\s+to\s+(.+)$', r'can you \1'),
        # "do you think you could X" → "can you X"
        (r'^do\s+you\s+think\s+you\s+could\s+(.+)$', r'can you \1'),
        # "i was hoping to X" → "X"
        (r'^i\s+was\s+hoping\s+to\s+(.+)$', r'\1'),
        # "looking to X" → "X"
        (r'^(i\'?m\s+)?looking\s+to\s+(.+)$', r'\2'),
        # "trying to find out X" → "X"
        (r'^(i\'?m\s+)?trying\s+to\s+find\s+out\s+(.+)$', r'\2'),
    ]
    
    for pattern, replacement in WRAPPER_PATTERNS:
        match = re.match(pattern, t, re.IGNORECASE)
        if match:
            result = re.sub(pattern, replacement, t, flags=re.IGNORECASE).strip()
            # Clean up any leftover awkwardness
            result = re.sub(r'^(about|if|whether)\s+', '', result)
            result = re.sub(r'\s+(please|pls)$', '', result)
            if len(result) >= 3:
                return result
    
    return t


def normalize_message(text: str) -> str:
    if not text:
        return ""
    t = text
    t = normalize_unicode(t)
    t = t.lower()
    t = expand_contractions(t)
    t = expand_slang(t)
    t = remove_fluff(t)
    t = extract_core_question(t)  # Extract core question from verbose phrasing
    t = normalize_whitespace(t)
    return t

