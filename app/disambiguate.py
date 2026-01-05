"""
LLM-based FAQ disambiguation for uncertain embedding matches.

When embedding retrieval returns scores between 0.50-0.82 (uncertain zone),
ask the LLM to pick the best matching FAQ from the top candidates.

This gives us the robustness of LLM understanding without:
- Generating hundreds of variants
- Learning from production traffic
- Lowering the embedding threshold
"""

import json
from typing import Optional
from app.openai_client import chat_once


DISAMBIGUATE_PROMPT = """You are helping match a customer question to FAQ answers.

Customer question: "{question}"

Here are the top FAQ candidates (ranked by similarity):

{candidates}

Which FAQ best answers the customer's question?

Rules:
- Pick the FAQ that DIRECTLY answers what the customer is asking
- If the customer asks about pricing, pick the pricing FAQ
- If the customer asks about licensing/insurance, pick the trust/credentials FAQ
- If NONE of the FAQs answer the question, say "none"
- Only pick a FAQ if you're confident it's the right match

Respond with ONLY the number (1, 2, 3, etc.) or "none". No explanation."""


def disambiguate_faq(
    question: str,
    candidates: list[dict],  # [{faq_id, question, answer, score}, ...]
    min_candidates: int = 2,
    max_candidates: int = 5
) -> Optional[dict]:
    """
    Ask LLM to pick the best FAQ match from uncertain candidates.
    
    Args:
        question: The normalized customer question
        candidates: List of FAQ candidates with scores
        min_candidates: Minimum candidates needed to disambiguate
        max_candidates: Maximum candidates to show LLM
    
    Returns:
        The best matching FAQ dict, or None if no match
    """
    if not candidates or len(candidates) < min_candidates:
        return None
    
    # Limit candidates
    candidates = candidates[:max_candidates]
    
    # Format candidates for prompt
    candidates_text = ""
    for i, c in enumerate(candidates, 1):
        candidates_text += f"\n{i}. FAQ: {c['question']}\n"
        candidates_text += f"   Answer preview: {c['answer'][:150]}...\n"
        candidates_text += f"   (similarity: {c['score']:.2f})\n"
    
    prompt = DISAMBIGUATE_PROMPT.format(
        question=question,
        candidates=candidates_text
    )
    
    try:
        response = chat_once(
            system="You are a precise FAQ matching assistant. Respond only with a number or 'none'.",
            user=prompt,
            temperature=0.0,  # Deterministic
            max_tokens=10
        )
        
        response = response.strip().lower()
        
        # Parse response
        if response == "none":
            return None
        
        # Try to extract number
        try:
            idx = int(response.replace(".", "").strip()) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except ValueError:
            pass
        
        return None
        
    except Exception as e:
        print(f"Disambiguate error: {e}")
        return None


def should_disambiguate(top_score: float, runner_up_score: float = 0) -> bool:
    """
    Decide if we should ask LLM to disambiguate.
    
    Returns True if:
    - Top score is in uncertain zone (0.50 - 0.82)
    - OR top two scores are very close (ambiguous)
    """
    THETA_HIGH = 0.82
    THETA_LOW = 0.50
    DELTA_AMBIGUOUS = 0.05
    
    # Uncertain zone
    if THETA_LOW <= top_score < THETA_HIGH:
        return True
    
    # Ambiguous (top two very close)
    if runner_up_score and (top_score - runner_up_score) < DELTA_AMBIGUOUS:
        return True
    
    return False

