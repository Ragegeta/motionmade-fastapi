"""Test FTS search."""
from app.retriever import search_fts

results = search_fts('sparkys_electrical', 'powerpoints')
print(f'FTS search for "powerpoints": {len(results)} results')
for r in results[:3]:
    print(f'  - {r["question"][:40]}... (score: {r.get("fts_score", 0):.3f})')

