#!/usr/bin/env python3
"""
Use LLM to generate additional variants for FAQs.

This catches phrasings that templates miss by asking the LLM:
"How might real users ask this question?"

Usage:
    python generate_variants_llm.py <faqs_path> [--output=<path>] [--max-per-faq=50]
"""

import json
import sys
import os
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.openai_client import chat_once


VARIANT_PROMPT = """You are helping improve a customer service FAQ system.

Given this FAQ question and its current variants, generate 20 MORE unique ways real users might ask this same question.

Include:
- Casual/informal versions ("hey", "quick q", etc.)
- Slang and typos ("ur", "u", "wat", "pls", etc.)
- Very short versions (1-3 words)
- Verbose versions (full sentences with filler words)
- Australian slang if relevant ("arvo", "reckon", etc.)
- Questions with extra punctuation ("???", "!!")
- ALL CAPS versions
- Misspellings of key words

FAQ Question: {question}
FAQ Answer Summary: {answer_summary}

Current variants (DO NOT repeat these):
{current_variants}

Return ONLY a JSON array of 20 new variant strings. No explanation, just the array.
Example format: ["variant 1", "variant 2", "variant 3", ...]
"""


def generate_variants_for_faq(faq: dict, max_new: int = 20) -> list:
    """Generate new variants for a single FAQ using LLM."""
    question = faq.get("question", "")
    answer = faq.get("answer", "")[:200]  # Truncate answer for prompt
    current = faq.get("variants", [])
    
    prompt = VARIANT_PROMPT.format(
        question=question,
        answer_summary=answer,
        current_variants="\n".join(f"- {v}" for v in current[:30])  # Limit context
    )
    
    try:
        response = chat_once(
            system="You are a helpful assistant that generates FAQ variants.",
            user=prompt,
            temperature=0.8  # Higher temp for variety
        )
        
        # Parse JSON array from response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        
        new_variants = json.loads(response)
        
        if not isinstance(new_variants, list):
            return []
        
        # Clean and dedupe
        new_variants = [v.strip().lower() for v in new_variants if isinstance(v, str)]
        current_lower = {v.lower() for v in current}
        new_variants = [v for v in new_variants if v and v not in current_lower]
        
        return new_variants[:max_new]
    
    except Exception as e:
        print(f"  Warning: LLM generation failed for '{question}': {e}")
        return []


def generate_variants_for_file(faqs_path: str, output_path: str = None, max_per_faq: int = 50):
    """Generate variants for all FAQs in a file."""
    with open(faqs_path, "r", encoding="utf-8") as f:
        faqs = json.load(f)
    
    total_before = sum(len(faq.get("variants", [])) for faq in faqs)
    
    print(f"Generating LLM variants for {len(faqs)} FAQs...")
    
    for i, faq in enumerate(faqs):
        current_count = len(faq.get("variants", []))
        
        if current_count >= max_per_faq:
            print(f"  [{i+1}/{len(faqs)}] '{faq['question']}' - already has {current_count} variants, skipping")
            continue
        
        print(f"  [{i+1}/{len(faqs)}] '{faq['question']}' - generating variants...", end=" ")
        
        new_variants = generate_variants_for_faq(faq, max_new=max_per_faq - current_count)
        
        if new_variants:
            faq["variants"] = faq.get("variants", []) + new_variants
            # Dedupe
            seen = set()
            unique = []
            for v in faq["variants"]:
                v_lower = v.lower().strip()
                if v_lower not in seen:
                    seen.add(v_lower)
                    unique.append(v)
            faq["variants"] = unique[:max_per_faq]
        
        print(f"+{len(new_variants)} → {len(faq.get('variants', []))} total")
    
    total_after = sum(len(faq.get("variants", [])) for faq in faqs)
    
    # Write output
    out_path = output_path or faqs_path
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(faqs, f, indent=2, ensure_ascii=False)
    
    print(f"\nExpanded: {total_before} → {total_after} variants (+{total_after - total_before})")
    print(f"Output: {out_path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    faqs_path = sys.argv[1]
    output_path = None
    max_per_faq = 50
    
    for arg in sys.argv[2:]:
        if arg.startswith("--output="):
            output_path = arg.split("=", 1)[1]
        elif arg.startswith("--max-per-faq="):
            max_per_faq = int(arg.split("=", 1)[1])
    
    generate_variants_for_file(faqs_path, output_path, max_per_faq)


if __name__ == "__main__":
    main()

