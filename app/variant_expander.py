"""
Automatic variant expansion for FAQs.

Given a FAQ question/answer, generates comprehensive variants covering:
1. Symptom-based queries (e.g., "smoke alarm" → "beeping", "chirping")
2. Synonyms (e.g., "powerpoint" → "outlet", "socket")
3. Question forms (e.g., "do you do X", "can you fix X", "X help")
4. Generic cost/payment/duration/area variants for any business type
5. Optional LLM-generated slang/casual/specific-scenario variants

This runs at FAQ upload/promote time, not query time.
"""

from typing import List, Optional
import re

# Generic intent phrases (any business) — question/answer substring -> list of customer phrasings
GENERIC_INTENT_VARIANTS = {
    "callout": ["how much for a plumber to come out", "plumber come out cost", "cost for someone to come out", "how much to come out", "callout fee", "what do you charge to come out"],
    "call out": ["how much for call out", "call out cost", "fee for coming out"],
    "cost": ["how much", "what does it cost", "whats the cost", "how much does it cost", "what do you charge"],
    "price": ["how much", "whats the price", "what are your prices", "pricing"],
    "fee": ["how much", "whats the fee", "fee for"],
    "charge": ["what do you charge", "how much do you charge", "charging"],
    "rate": ["whats your rate", "hourly rate", "rates"],
    "payment": ["can i pay later", "pay later", "payment plans", "pay in instalments", "how do i pay", "payment methods", "what payment do you accept"],
    "afterpay": ["pay later", "can i pay later", "afterpay", "pay in instalments", "payment plans"],
    "pay later": ["can i pay later", "pay later", "payment plans", "afterpay"],
    "how long": ["how long does it take", "how long to fix", "how long will it take", "how long fix my tap", "how long for a job", "duration"],
    "typical job": ["how long to fix my tap", "how long fix a tap", "how long does a job take"],
    "minutes": ["how long", "how long does it take", "how many minutes"],
    "hours": ["how long", "how many hours"],
    "areas": ["what areas do you cover", "what areas u cover", "do you come to", "what suburbs", "do you service"],
    "service": ["what areas", "do you service", "where do you go"],
    "cover": ["what areas do you cover", "do you cover", "do you come to"],
    "book": ["how do i book", "how to book", "how do i book a clean", "booking"],
    "quote": ["free quote", "do you give quotes", "how much for a quote"],
    "licensed": ["are you licensed", "r u licensed", "do you have a licence"],
    "emergency": ["do you do emergency", "emergency stuff", "urgent", "asap"],
    "weekend": ["are you available on weekends", "weekends", "saturday", "sunday"],
}

# Synonym mappings (electrical industry)
SYNONYMS = {
    "powerpoint": ["power point", "outlet", "socket", "gpo", "power outlet", "electrical outlet"],
    "switchboard": ["electrical panel", "fuse box", "distribution board", "meter box", "main board"],
    "ceiling fan": ["fan", "ceiling fans"],
    "smoke alarm": ["smoke detector", "fire alarm", "detector"],
    "safety switch": ["rcd", "residual current device", "safety switches", "circuit breaker"],
    "lighting": ["lights", "light", "light fixture", "light fitting"],
    "wiring": ["rewire", "rewiring", "electrical wiring", "cables"],
    "emergency": ["urgent", "asap", "right now", "immediately", "no power", "power out", "blackout"],
}

# Symptom mappings (what customers describe vs what service they need)
SYMPTOM_MAPPINGS = {
    "smoke alarm": [
        "beeping", "chirping", "won't stop beeping", "keeps beeping",
        "annoying beep", "beeping sound", "chirping noise", "battery low",
        "false alarm", "going off", "keeps going off"
    ],
    "lighting": [
        "flickering", "flicker", "dimming", "dim", "lights dim",
        "lights flicker", "turning off", "won't turn on", "not working",
        "keeps turning off", "goes off randomly"
    ],
    "safety switch": [
        "tripping", "keeps tripping", "cutting power", "power cuts out",
        "everything shuts off", "keeps cutting out", "won't stay on"
    ],
    "powerpoint": [
        "not working", "dead", "no power", "sparking", "burnt",
        "loose", "broken", "cracked"
    ],
    "switchboard": [
        "buzzing", "humming", "hot", "burning smell", "old", "outdated",
        "needs replacing", "upgrade needed"
    ],
    "emergency": [
        "no power", "power out", "blackout", "everything off",
        "smell burning", "sparks", "electrical fire", "shock", "got shocked"
    ],
}

# Question form templates
QUESTION_FORMS = [
    "{keyword}",
    "do you do {keyword}",
    "can you do {keyword}",
    "do you fix {keyword}",
    "can you fix {keyword}",
    "help with {keyword}",
    "{keyword} help",
    "{keyword} service",
    "{keyword} repair",
    "{keyword} installation",
    "need help with {keyword}",
    "problem with {keyword}",
    "{keyword} issue",
    "{keyword} not working",
]


def extract_keywords(text: str) -> List[str]:
    """Extract potential service keywords from FAQ text."""
    text_lower = text.lower()
    found = []
    
    # Check for known service keywords (electrical)
    all_keywords = list(SYNONYMS.keys()) + list(SYMPTOM_MAPPINGS.keys())
    for keyword in all_keywords:
        if keyword in text_lower:
            found.append(keyword)
    
    return list(set(found))


def add_generic_intent_variants(question: str, answer: str) -> List[str]:
    """Add variants from generic intent phrases (cost, payment, duration, areas, etc.)."""
    combined = (question + " " + answer).lower()
    out = []
    for key, phrasings in GENERIC_INTENT_VARIANTS.items():
        if key in combined:
            out.extend(phrasings)
    return list(set(out))


def add_answer_specific_variants(question: str, answer: str) -> List[str]:
    """Extract concrete nouns from answer (e.g. tap, bond, oven) and add 'how long to fix X' style variants."""
    # Words in answer that often indicate specific scenarios (3–8 chars, not stopwords)
    stop = {"the", "and", "for", "with", "you", "your", "this", "that", "from", "are", "have", "will", "can", "all", "our", "yes", "not"}
    words = re.findall(r"\b[a-z]{3,8}\b", (answer or "").lower())
    specifics = [w for w in words if w not in stop and w.isalpha()]
    if not specifics:
        return []
    q_lower = (question or "").lower()
    out = []
    # If question is about duration/time, add "how long to fix [specific]"
    if "how long" in q_lower or "take" in q_lower or "minutes" in q_lower or "hours" in q_lower:
        for s in specifics[:5]:
            out.append(f"how long to fix {s}")
            out.append(f"how long fix my {s}")
    return out


def expand_with_synonyms(keywords: List[str]) -> List[str]:
    """Expand keywords with their synonyms."""
    expanded = []
    for kw in keywords:
        expanded.append(kw)
        if kw in SYNONYMS:
            expanded.extend(SYNONYMS[kw])
    return list(set(expanded))


def expand_with_symptoms(keywords: List[str]) -> List[str]:
    """Expand keywords with symptom-based phrases."""
    expanded = []
    for kw in keywords:
        if kw in SYMPTOM_MAPPINGS:
            for symptom in SYMPTOM_MAPPINGS[kw]:
                expanded.append(f"{kw} {symptom}")
                expanded.append(symptom)
    return list(set(expanded))


def expand_with_question_forms(keywords: List[str]) -> List[str]:
    """Expand keywords with question form variations."""
    expanded = []
    for kw in keywords:
        for template in QUESTION_FORMS:
            expanded.append(template.format(keyword=kw))
    return list(set(expanded))


def generate_variants_llm(question: str, answer: str, max_extra: int = 18) -> List[str]:
    """Use GPT-4o-mini to generate diverse phrasings: slang, casual, specific-scenario, synonyms."""
    try:
        from .openai_client import chat_once
        prompt = f"""Generate {max_extra} short alternative phrasings that customers might use to ask this question. Include:
- Text-speak/slang: "hw much", "wat", "u", "4", "r u", "do u"
- Casual: "how much 4", "can i pay later", "wats included"
- Specific scenarios: if the answer mentions something (e.g. tap, bond), include "how long to fix tap" style
- Synonyms: cost/price/charge/fee/rate, pay later/afterpay/payment plans
- Question forms: "Do you do X?", "Can you X?", "Is X available?", "What about X?"
Return ONLY one phrasing per line, no numbers or bullets. Lowercase. Keep each under 10 words where possible.

Question: {question}
Answer (for context): {answer[:200]}"""
        reply = chat_once(
            "You output only alternative phrasings, one per line. No other text.",
            prompt,
            temperature=0.7,
            max_tokens=400,
            timeout=10,
        )
        if not reply:
            return []
        lines = [ln.strip().lower() for ln in reply.strip().splitlines() if ln.strip() and len(ln.strip()) > 4]
        return lines[:max_extra]
    except Exception:
        return []


def generate_variants(question: str, answer: str, max_variants: int = 50) -> List[str]:
    """
    Generate comprehensive variants for a FAQ (15–20+ diverse variants).
    """
    # Start with the original question
    variants = [question.lower()]
    
    # 1. Generic intent variants (cost, payment, duration, areas, etc.)
    variants.extend(add_generic_intent_variants(question, answer))
    
    # 2. Answer-specific (e.g. "how long to fix tap" when answer mentions tap)
    variants.extend(add_answer_specific_variants(question, answer))
    
    # 3. Electrical/service keywords (existing)
    keywords = extract_keywords(question + " " + answer)
    if keywords:
        variants.extend(expand_with_synonyms(keywords))
        variants.extend(expand_with_symptoms(keywords))
        variants.extend(expand_with_question_forms(keywords[:3]))
    
    # 4. LLM-generated slang/casual/specific variants (aim for 15–20 total per FAQ)
    try:
        llm_variants = generate_variants_llm(question, answer, max_extra=18)
        variants.extend(llm_variants)
    except Exception:
        pass
    
    # Dedupe and clean
    seen = set()
    unique = []
    for v in variants:
        v_clean = (v or "").strip().lower()
        if v_clean and v_clean not in seen and len(v_clean) > 2:
            seen.add(v_clean)
            unique.append(v_clean)
    
    return unique[:max_variants]


def expand_faq_list(faqs: List[dict], max_variants_per_faq: int = 50) -> List[dict]:
    """
    Expand variants for a list of FAQs.
    
    Args:
        faqs: List of {"question": ..., "answer": ..., "variants": [...]}
        max_variants_per_faq: Max variants per FAQ
    
    Returns:
        Same list with expanded variants
    """
    for faq in faqs:
        question = faq.get("question", "")
        answer = faq.get("answer", "")
        existing_variants = faq.get("variants", [])
        
        # Generate new variants
        generated = generate_variants(question, answer, max_variants_per_faq)
        
        # Merge with existing (existing take priority)
        all_variants = list(existing_variants) + generated
        
        # Dedupe
        seen = set()
        unique = []
        for v in all_variants:
            v_lower = v.lower().strip()
            if v_lower not in seen:
                seen.add(v_lower)
                unique.append(v)
        
        faq["variants"] = unique[:max_variants_per_faq]
    
    return faqs


