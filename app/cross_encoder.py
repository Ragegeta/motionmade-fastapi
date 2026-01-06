"""
Cross-encoder reranking for FAQ retrieval.

Cross-encoders see query AND document together, understanding relationships
that bi-encoders (separate embeddings) miss.

Example:
  Query: "do you do plumbing"
  FAQ: "We handle electrical work: powerpoints, lighting..."
  
  Bi-encoder score: 0.45 (both mention "do")
  Cross-encoder score: 0.08 (understands plumbing ≠ electrical)

Options:
1. Cohere Rerank API (fast to test, $1/1000 queries)
2. Self-hosted sentence-transformers (free, ~100-200ms CPU)
3. ONNX optimized (free, ~50-100ms CPU)

We'll implement Option 2 (self-hosted) with Option 1 (Cohere) as fallback.
"""

import os
import time
from typing import Optional
import httpx
import numpy as np

# Try to import sentence-transformers (self-hosted option)
try:
    from sentence_transformers import CrossEncoder
    CROSS_ENCODER_MODEL = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    SELF_HOSTED_AVAILABLE = True
    print("Cross-encoder: Using self-hosted ms-marco-MiniLM-L-6-v2")
except ImportError:
    CROSS_ENCODER_MODEL = None
    SELF_HOSTED_AVAILABLE = False
    print("Cross-encoder: sentence-transformers not installed, will use Cohere API")

# Cohere API (fallback)
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
COHERE_RERANK_URL = "https://api.cohere.ai/v1/rerank"

# Thresholds (after sigmoid normalization to 0-1)
RERANK_THRESHOLD = 0.3  # Below this = reject (cross-encoder is confident it's wrong)
RERANK_HIGH_CONFIDENCE = 0.7  # Above this = confident match


def rerank_self_hosted(
    query: str,
    candidates: list[dict],
    top_k: int = 5
) -> tuple[list[dict], dict]:
    """
    Rerank candidates using self-hosted cross-encoder.
    
    Args:
        query: Normalized user query
        candidates: List of {faq_id, question, answer, score, ...}
        top_k: Number of results to return
    
    Returns:
        (reranked_candidates, trace)
    """
    trace = {
        "method": "self_hosted",
        "model": "ms-marco-MiniLM-L-6-v2",
        "input_count": len(candidates),
        "duration_ms": 0,
        "scores": []
    }
    
    if not SELF_HOSTED_AVAILABLE or not CROSS_ENCODER_MODEL:
        trace["error"] = "model_not_available"
        return candidates[:top_k], trace
    
    if not candidates:
        return [], trace
    
    start_time = time.time()
    
    try:
        # Create query-document pairs
        pairs = [
            (query, f"{c['question']} {c['answer'][:200]}")
            for c in candidates
        ]
        
        # Get cross-encoder scores (raw logits, can be negative)
        raw_scores = CROSS_ENCODER_MODEL.predict(pairs)
        
        # Normalize using sigmoid to 0-1 range for easier thresholding
        import numpy as np
        scores = 1 / (1 + np.exp(-np.array(raw_scores)))
        
        # Attach normalized scores to candidates
        for i, c in enumerate(candidates):
            c['rerank_score'] = float(scores[i])
        
        # Sort by rerank score
        reranked = sorted(candidates, key=lambda x: x['rerank_score'], reverse=True)
        
        trace["duration_ms"] = int((time.time() - start_time) * 1000)
        trace["scores"] = [round(s, 4) for s in scores[:5]]
        
        return reranked[:top_k], trace
        
    except Exception as e:
        trace["error"] = str(e)[:100]
        trace["duration_ms"] = int((time.time() - start_time) * 1000)
        return candidates[:top_k], trace


def rerank_cohere(
    query: str,
    candidates: list[dict],
    top_k: int = 5
) -> tuple[list[dict], dict]:
    """
    Rerank candidates using Cohere Rerank API.
    
    Args:
        query: Normalized user query
        candidates: List of {faq_id, question, answer, score, ...}
        top_k: Number of results to return
    
    Returns:
        (reranked_candidates, trace)
    """
    trace = {
        "method": "cohere_api",
        "model": "rerank-english-v3.0",
        "input_count": len(candidates),
        "duration_ms": 0,
        "scores": []
    }
    
    if not COHERE_API_KEY:
        trace["error"] = "no_api_key"
        return candidates[:top_k], trace
    
    if not candidates:
        return [], trace
    
    start_time = time.time()
    
    try:
        # Prepare documents for Cohere
        documents = [
            f"{c['question']} {c['answer'][:200]}"
            for c in candidates
        ]
        
        # Call Cohere API
        response = httpx.post(
            COHERE_RERANK_URL,
            headers={
                "Authorization": f"Bearer {COHERE_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "rerank-english-v3.0",
                "query": query,
                "documents": documents,
                "top_n": min(top_k, len(documents))
            },
            timeout=5.0
        )
        
        if response.status_code != 200:
            trace["error"] = f"api_error_{response.status_code}"
            trace["duration_ms"] = int((time.time() - start_time) * 1000)
            return candidates[:top_k], trace
        
        result = response.json()
        
        # Map scores back to candidates
        reranked = []
        for r in result.get("results", []):
            idx = r["index"]
            candidates[idx]["rerank_score"] = r["relevance_score"]
            reranked.append(candidates[idx])
        
        trace["duration_ms"] = int((time.time() - start_time) * 1000)
        trace["scores"] = [round(r["relevance_score"], 4) for r in result.get("results", [])[:5]]
        
        return reranked, trace
        
    except Exception as e:
        trace["error"] = str(e)[:100]
        trace["duration_ms"] = int((time.time() - start_time) * 1000)
        return candidates[:top_k], trace


def rerank(
    query: str,
    candidates: list[dict],
    top_k: int = 5,
    prefer_self_hosted: bool = True
) -> tuple[list[dict], dict]:
    """
    Rerank candidates using best available method.
    
    Tries self-hosted first (free, fast), falls back to Cohere API.
    
    Returns:
        (reranked_candidates, trace)
    """
    if prefer_self_hosted and SELF_HOSTED_AVAILABLE:
        return rerank_self_hosted(query, candidates, top_k)
    elif COHERE_API_KEY:
        return rerank_cohere(query, candidates, top_k)
    else:
        # No reranking available, return as-is
        return candidates[:top_k], {"method": "none", "error": "no_reranker_available"}


def should_accept(rerank_score: float) -> tuple[bool, str]:
    """
    Decide whether to accept a reranked result.
    
    Returns:
        (accept, reason)
    """
    if rerank_score >= RERANK_HIGH_CONFIDENCE:
        return True, "high_confidence"
    elif rerank_score >= RERANK_THRESHOLD:
        return True, "acceptable"
    else:
        return False, f"below_threshold_{rerank_score:.2f}"

