"""Test LLM selector fallback."""
from app.retriever import retrieve

# Test with a query
result, trace = retrieve(
    tenant_id='sparkys_electrical',
    query='are you licensed',
    normalized_query='are you licensed',
    use_cache=False
)

print(f'Result: {"HIT" if result else "MISS"}')
print(f'Stage: {trace.get("stage", "?")}')
print(f'Selector called: {trace.get("selector_called", False)}')
print(f'Selector confidence: {trace.get("selector_confidence", 0)}')
print(f'Final score: {trace.get("final_score", 0)}')
print(f'Rerank method: {trace.get("rerank_trace", {}).get("method", "?")}')
print(f'Accept reason: {trace.get("accept_reason", "?")}')


