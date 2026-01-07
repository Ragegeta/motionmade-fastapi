"""
Automatic variant expansion for FAQs.

Given a FAQ question/answer, generates comprehensive variants covering:
1. Symptom-based queries (e.g., "smoke alarm" → "beeping", "chirping")
2. Synonyms (e.g., "powerpoint" → "outlet", "socket")
3. Question forms (e.g., "do you do X", "can you fix X", "X help")

This runs at FAQ upload/promote time, not query time.
"""

from typing import List
import re

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
    
    # Check for known service keywords
    all_keywords = list(SYNONYMS.keys()) + list(SYMPTOM_MAPPINGS.keys())
    for keyword in all_keywords:
        if keyword in text_lower:
            found.append(keyword)
    
    return list(set(found))


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


def generate_variants(question: str, answer: str, max_variants: int = 50) -> List[str]:
    """
    Generate comprehensive variants for a FAQ.
    
    Args:
        question: The FAQ question/title
        answer: The FAQ answer (used to extract keywords)
        max_variants: Maximum number of variants to return
    
    Returns:
        List of variant strings
    """
    # Start with the original question
    variants = [question.lower()]
    
    # Extract keywords from question and answer
    keywords = extract_keywords(question + " " + answer)
    
    if not keywords:
        # No known keywords, just return basic variants
        return variants[:max_variants]
    
    # Expand with synonyms
    synonym_variants = expand_with_synonyms(keywords)
    variants.extend(synonym_variants)
    
    # Expand with symptoms
    symptom_variants = expand_with_symptoms(keywords)
    variants.extend(symptom_variants)
    
    # Expand with question forms (for original keywords only, not all synonyms)
    question_variants = expand_with_question_forms(keywords[:3])  # Limit to top 3 keywords
    variants.extend(question_variants)
    
    # Dedupe and clean
    seen = set()
    unique = []
    for v in variants:
        v_clean = v.strip().lower()
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


