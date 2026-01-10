#!/usr/bin/env python3
"""Analyze confidence pack results."""
import json
import sys
from pathlib import Path

def analyze_confidence_json(json_path):
    """Analyze confidence pack results."""
    with open(json_path, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)
    
    # Get cases - might be under 'results' or 'cases'
    cases = data.get('results', data.get('cases', []))
    total = len(cases)
    
    if total == 0:
        print(f"No cases found in {json_path}")
        return
    
    # Count FTS-only and vector usage
    fts_only = 0
    vector_ran = 0
    selector_called = 0
    
    # Stats for cases where vector ran
    vector_retrieval_times = []
    vector_total_times = []
    
    # Track slowest cases
    slowest_cases = []
    
    for i, case in enumerate(cases):
        headers = case.get('headers', {})
        
        # Check FTS-only
        fts_only_val = headers.get('x-retrieval-used-fts-only', '0')
        if fts_only_val in ('1', 1, True, 'true'):
            fts_only += 1
        
        # Check vector ran
        vector_val = headers.get('x-retrieval-ran-vector', '0')
        if vector_val in ('1', 1, True, 'true'):
            vector_ran += 1
            
            # Collect timing data for vector cases
            retrieval_vector_ms = (case.get('timing_retrieval_vector_ms') or 
                                  headers.get('x-timing-retrieval-vector') or
                                  headers.get('x-retrieval-vector-ms'))
            retrieval_total_ms = (case.get('timing_retrieval_ms') or 
                                 headers.get('x-retrieval-ms') or
                                 headers.get('x-timing-retrieval'))
            total_retrieval_ms = (case.get('timing_total_ms') or 
                                 headers.get('x-timing-total') or
                                 headers.get('x-timing-retrieval'))
            
            if retrieval_vector_ms:
                try:
                    vector_retrieval_times.append(float(retrieval_vector_ms))
                except (ValueError, TypeError):
                    pass
            
            if total_retrieval_ms:
                try:
                    vector_total_times.append(float(total_retrieval_ms))
                except (ValueError, TypeError):
                    pass
        
        # Check selector called (header uses "1"/"0" format, like x-retrieval-used-fts-only)
        selector_val = headers.get('x-selector-called', '0')
        if selector_val in ('1', 1, True, 'true', 'True'):
            selector_called += 1
        
        # Track slowest cases
        total_time = (case.get('timing_total_ms') or 
                     case.get('total_case_ms') or 
                     case.get('http_latency_ms') or
                     headers.get('x-timing-total') or
                     headers.get('x-retrieval-ms') or
                     0)
        query = case.get('input') or case.get('normalized_input', 'unknown')
        # Determine path type: fts-only if used_fts_only=1, otherwise vector (even if vector didn't run, it's not fts-only)
        path_type = 'fts-only' if fts_only_val in ('1', 1, True, 'true') else ('vector' if vector_val in ('1', 1, True, 'true') else 'none')
        slowest_cases.append({
            'index': i,
            'query': query,
            'path': path_type,
            'total_ms': float(total_time) if total_time else 0,
            'fts_only': fts_only_val == '1' or fts_only_val == 1,
            'vector_ran': vector_val == '1' or vector_val == 1,
            'selector_called': selector_val == '1' or selector_val == 1
        })
    
    # Sort slowest cases
    slowest_cases.sort(key=lambda x: x['total_ms'], reverse=True)
    
    # Print results
    print(f"=" * 80)
    print(f"CONFIDENCE PACK ANALYSIS")
    print(f"=" * 80)
    print(f"\nTotal cases: {total}")
    print(f"\nFTS-only usage:")
    print(f"  Cases with x-retrieval-used-fts-only=1: {fts_only} ({fts_only/total*100:.1f}%)")
    print(f"\nVector usage:")
    print(f"  Cases with x-retrieval-ran-vector=1: {vector_ran} ({vector_ran/total*100:.1f}%)")
    print(f"\nSelector called:")
    print(f"  Cases with x-selector-called=1/true: {selector_called} ({selector_called/total*100:.1f}%)")
    
    if vector_retrieval_times:
        vector_retrieval_times.sort()
        p50_idx = len(vector_retrieval_times) // 2
        p95_idx = int(len(vector_retrieval_times) * 0.95)
        
        print(f"\nVector retrieval timing (cases where vector ran):")
        print(f"  Count: {len(vector_retrieval_times)}")
        print(f"  p50: {vector_retrieval_times[p50_idx]:.1f}ms")
        print(f"  p95: {vector_retrieval_times[p95_idx]:.1f}ms")
    
    if vector_total_times:
        vector_total_times.sort()
        p50_idx = len(vector_total_times) // 2
        p95_idx = int(len(vector_total_times) * 0.95)
        
        print(f"\nTotal retrieval timing (cases where vector ran):")
        print(f"  Count: {len(vector_total_times)}")
        print(f"  p50: {vector_total_times[p50_idx]:.1f}ms")
        print(f"  p95: {vector_total_times[p95_idx]:.1f}ms")
    
    print(f"\n10 Slowest cases:")
    for i, case_info in enumerate(slowest_cases[:10], 1):
        path_desc = case_info['path']
        if case_info.get('selector_called'):
            path_desc += '+selector'
        print(f"  {i}. [{path_desc}] {case_info['total_ms']:.1f}ms - \"{case_info['query'][:80]}\"")

if __name__ == '__main__':
    json_path = sys.argv[1] if len(sys.argv) > 1 else 'tools/results/confidence_sparkys_electrical_20260110_171832.json'
    analyze_confidence_json(json_path)

