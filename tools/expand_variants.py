#!/usr/bin/env python3
"""
Offline Variant Expansion Tool

Generates additional FAQ variants using deterministic templates and transformations.
This improves robustness without lowering THETA threshold.

Features:
- Question starter/ender templates
- Slang replacements (u/ur/pls/wat/etc)
- Key-term short forms
- Hard cap: max 30 variants per FAQ
- Deduplication and normalization
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Set


# Question starter templates
QUESTION_STARTERS = [
    "",
    "what is",
    "what are",
    "what's",
    "whats",
    "how much",
    "how many",
    "how do",
    "how does",
    "how can",
    "do you",
    "does",
    "can you",
    "can i",
    "is there",
    "are there",
    "tell me about",
    "i need",
    "i want",
    "i'm looking for",
    "quick question",
    "hey",
    "hi",
]

# Question ender templates
QUESTION_ENDERS = [
    "",
    "?",
    " please",
    " pls",
    " thanks",
    " thx",
    " thank you",
]

# Slang replacements (word -> replacements)
SLANG_REPLACEMENTS = {
    "you": ["u", "ya"],
    "your": ["ur", "yr"],
    "please": ["pls", "plz"],
    "what": ["wat", "wut"],
    "are": ["r"],
    "to": ["2"],
    "for": ["4"],
    "be": ["b"],
    "see": ["c"],
    "the": ["da"],
    "and": ["&", "n"],
    "with": ["w/", "wit"],
}

# Key-term short forms (common abbreviations)
KEY_TERM_SHORT_FORMS = {
    "pricing": ["price", "cost", "rate", "rates", "fee", "fees"],
    "quote": ["quote", "quotes", "estimate", "estimates"],
    "service": ["service", "services", "work"],
    "cleaning": ["clean", "cleaning", "cleaner", "cleaners"],
    "booking": ["book", "booking", "schedule", "appointment"],
    "availability": ["available", "avail", "when"],
    "cancellation": ["cancel", "cancellation", "cancelled"],
    "payment": ["pay", "payment", "payments", "paid"],
    "insurance": ["insured", "insurance", "coverage"],
    "area": ["areas", "location", "locations", "suburbs", "suburb"],
    "travel": ["travel", "traveling", "distance"],
    "parking": ["park", "parking", "spot"],
    "pets": ["pet", "pets", "animals", "dogs", "cats"],
    "supplies": ["supply", "supplies", "equipment", "products"],
    "eco": ["eco-friendly", "green", "environmental"],
    "oven": ["oven", "stove"],
    "fridge": ["fridge", "refrigerator", "refrigerator"],
    "deep": ["deep", "thorough", "detailed"],
    "standard": ["standard", "regular", "basic"],
    "bond": ["bond", "end-of-lease", "vacate"],
}


def normalize_variant(text: str) -> str:
    """Normalize variant text for deduplication."""
    if not text:
        return ""
    text = text.strip().lower()
    # Remove extra whitespace
    text = re.sub(r"\s+", " ", text)
    return text


def apply_slang_replacements(text: str) -> List[str]:
    """Generate slang variants of a text."""
    variants = [text]
    
    # Apply each slang replacement
    for standard, slangs in SLANG_REPLACEMENTS.items():
        for slang in slangs:
            # Replace whole word only (case-insensitive)
            pattern = r"\b" + re.escape(standard) + r"\b"
            if re.search(pattern, text, re.IGNORECASE):
                variant = re.sub(pattern, slang, text, flags=re.IGNORECASE)
                if variant != text:
                    variants.append(variant)
    
    return variants


def extract_key_terms(text: str) -> Set[str]:
    """Extract key terms from text that might have short forms."""
    text_lower = text.lower()
    found_terms = set()
    
    for term, short_forms in KEY_TERM_SHORT_FORMS.items():
        # Check if any form of the term appears
        for form in [term] + short_forms:
            if form in text_lower:
                found_terms.add(term)
                break
    
    return found_terms


def generate_key_term_variants(text: str) -> List[str]:
    """Generate variants by replacing key terms with their short forms."""
    variants = [text]
    key_terms = extract_key_terms(text)
    
    for term in key_terms:
        short_forms = KEY_TERM_SHORT_FORMS.get(term, [])
        for short_form in short_forms:
            # Replace whole word only (case-insensitive)
            pattern = r"\b" + re.escape(term) + r"\b"
            if re.search(pattern, text, re.IGNORECASE):
                variant = re.sub(pattern, short_form, text, flags=re.IGNORECASE)
                if variant != text:
                    variants.append(variant)
    
    return variants


def generate_template_variants(question: str) -> List[str]:
    """Generate variants using question starter/ender templates."""
    variants = []
    
    # Extract core question (remove existing starters/enders)
    core = question.strip()
    # Remove trailing question mark
    if core.endswith("?"):
        core = core[:-1].strip()
    
    # If question already starts with a starter, try without it
    core_no_starter = core
    for starter in QUESTION_STARTERS:
        if starter and core.lower().startswith(starter.lower()):
            core_no_starter = core[len(starter):].strip()
            break
    
    # Generate combinations
    for starter in QUESTION_STARTERS:
        for ender in QUESTION_ENDERS:
            if starter and ender:
                variant = f"{starter} {core_no_starter}{ender}".strip()
            elif starter:
                variant = f"{starter} {core_no_starter}".strip()
            elif ender:
                variant = f"{core_no_starter}{ender}".strip()
            else:
                variant = core_no_starter
            
            if variant and variant != question:
                variants.append(variant)
    
    return variants


def expand_faq_variants(faq: Dict) -> List[str]:
    """
    Generate expanded variants for a single FAQ.
    Returns list of variants (including original question).
    """
    question = faq.get("question", "").strip()
    if not question:
        return []
    
    existing_variants = faq.get("variants", [])
    
    # Start with original question and existing variants
    all_variants = [question]
    all_variants.extend(existing_variants)
    
    # 1. Template variants (starter/ender combinations)
    template_variants = generate_template_variants(question)
    all_variants.extend(template_variants)
    
    # 2. Slang replacements
    slang_variants = []
    for variant in all_variants[:]:  # Copy list to avoid modification during iteration
        slang_variants.extend(apply_slang_replacements(variant))
    all_variants.extend(slang_variants)
    
    # 3. Key-term short forms
    key_term_variants = []
    for variant in all_variants[:]:
        key_term_variants.extend(generate_key_term_variants(variant))
    all_variants.extend(key_term_variants)
    
    # Deduplicate and normalize
    seen = set()
    unique_variants = []
    
    for variant in all_variants:
        normalized = normalize_variant(variant)
        if normalized and len(normalized) >= 3 and normalized not in seen:
            seen.add(normalized)
            unique_variants.append(variant.strip())
    
    # Hard cap: max 30 variants per FAQ
    if len(unique_variants) > 30:
        # Keep original question first, then existing variants, then others
        original = unique_variants[0] if unique_variants else ""
        existing_set = set(normalize_variant(v) for v in existing_variants)
        
        # Prioritize: original, existing, then others
        prioritized = [original] if original else []
        others = []
        
        for v in unique_variants[1:]:
            if normalize_variant(v) in existing_set:
                prioritized.append(v)
            else:
                others.append(v)
        
        # Combine and cap
        unique_variants = prioritized + others[:30 - len(prioritized)]
    
    return unique_variants


def expand_faqs_file(input_path: Path, output_path: Path, overwrite: bool = False):
    """
    Expand variants for all FAQs in a JSON file.
    
    Args:
        input_path: Path to input FAQs JSON file
        output_path: Path to output expanded FAQs JSON file
        overwrite: If True and output_path exists, overwrite it
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {output_path}. "
            "Use --overwrite to overwrite."
        )
    
    # Load FAQs
    with open(input_path, "r", encoding="utf-8") as f:
        faqs = json.load(f)
    
    if not isinstance(faqs, list):
        raise ValueError("Input JSON must be a list of FAQ objects")
    
    # Expand variants for each FAQ
    expanded_faqs = []
    total_variants_before = 0
    total_variants_after = 0
    
    for faq in faqs:
        existing_count = len(faq.get("variants", []))
        total_variants_before += existing_count
        
        expanded_variants = expand_faq_variants(faq)
        
        # Create new FAQ object with expanded variants
        expanded_faq = {
            "question": faq.get("question", ""),
            "answer": faq.get("answer", ""),
            "variants": expanded_variants[1:] if len(expanded_variants) > 1 else []  # Exclude original question
        }
        
        # Preserve any other fields
        for key, value in faq.items():
            if key not in ["question", "answer", "variants"]:
                expanded_faq[key] = value
        
        expanded_faqs.append(expanded_faq)
        total_variants_after += len(expanded_variants) - 1  # Exclude original question
    
    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(expanded_faqs, f, indent=2, ensure_ascii=False)
    
    print(f"Expanded {len(faqs)} FAQs")
    print(f"  Variants before: {total_variants_before}")
    print(f"  Variants after: {total_variants_after}")
    print(f"  Average per FAQ: {total_variants_after / len(faqs):.1f}")
    print(f"Output written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Expand FAQ variants using deterministic templates and transformations"
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input FAQs JSON file (e.g., tenants/<tenantId>/faqs.json)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output expanded FAQs JSON file (e.g., tenants/<tenantId>/faqs_expanded.json)"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output file if it exists"
    )
    
    args = parser.parse_args()
    
    try:
        expand_faqs_file(args.input, args.output, overwrite=args.overwrite)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

