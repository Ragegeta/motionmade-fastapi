#!/usr/bin/env python3
"""Detailed analysis of confidence pack results for FTS gating optimization."""
import json
import sys
from collections import defaultdict
from pathlib import Path

def analyze_confidence_detailed(json_path):
    """Analyze confidence pack results in detail."""
    with open(json_path, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)
    
    cases = data.get('results', data.get('cases', []))
    total = len(cases)
    
    if total == 0:
        print(f"No cases found in {json_path}")
        return
    
    # Track distributions
    fts_only_count = 0
    vector_ran_count = 0
    both_count = 0
    
    # FTS score distributions
    fts_top_scores = []
    fts_gaps = []
    fts_candidate_counts = []
    
    # Cases where vector ran - what were FTS stats?
    vector_cases_fts_stats = []
    
    # Track all cases for detailed analysis
    all_case_stats = []
    
    for case in cases:
        headers = case.get('headers', {})
        
        fts_only_val = headers.get('x-retrieval-used-fts-only', '0')
        vector_val = headers.get('x-retrieval-ran-vector', '0')
        fts_candidates_val = headers.get('x-retrieval-fts-candidates', '0')
        
        fts_only = (fts_only_val == '1' or fts_only_val == 1)
        vector_ran = (vector_val == '1' or vector_val == 1)
        
        # Try to get FTS scores from headers or trace
        # FTS scores might not be directly in headers, but we can infer from retrieval stage
        retrieval_stage = headers.get('x-retrieval-stage', 'unknown')
        retrieval_mode = headers.get('x-retrieval-mode', 'unknown')
        
        fts_count = int(fts_candidates_val) if fts_candidates_val else 0
        fts_candidate_counts.append(fts_count)
        
        # Try to get FTS top score - might need to check raw headers or trace
        # For now, we'll note that we don't have direct access to FTS scores in the JSON
        # But we can analyze what we have
        
        case_stat = {
            'query': case.get('input') or case.get('normalized_input', 'unknown'),
            'fts_only': fts_only,
            'vector_ran': vector_ran,
            'fts_candidate_count': fts_count,
            'retrieval_stage': retrieval_stage,
            'retrieval_mode': retrieval_mode,
            'faq_hit': case.get('faq_hit', False)
        }
        all_case_stats.append(case_stat)
        
        if fts_only:
            fts_only_count += 1
        if vector_ran:
            vector_ran_count += 1
            # For vector cases, track FTS stats
            vector_cases_fts_stats.append({
                'fts_candidate_count': fts_count,
                'retrieval_stage': retrieval_stage,
                'faq_hit': case.get('faq_hit', False)
            })
        if fts_only and vector_ran:
            both_count += 1
    
    # Print summary
    print("=" * 80)
    print("DETAILED CONFIDENCE PACK ANALYSIS")
    print("=" * 80)
    print(f"\nTotal cases: {total}")
    print(f"\n1. DISTRIBUTION:")
    print(f"   FTS-only (x-retrieval-used-fts-only=1): {fts_only_count} ({fts_only_count/total*100:.1f}%)")
    print(f"   Vector ran (x-retrieval-ran-vector=1): {vector_ran_count} ({vector_ran_count/total*100:.1f}%)")
    print(f"   Both (shouldn't happen): {both_count}")
    print(f"   Neither: {total - fts_only_count - vector_ran_count + both_count}")
    
    print(f"\n2. FTS CANDIDATE COUNT DISTRIBUTION:")
    fts_count_dist = defaultdict(int)
    for count in fts_candidate_counts:
        if count == 0:
            fts_count_dist['0'] += 1
        elif count == 1:
            fts_count_dist['1'] += 1
        elif count <= 3:
            fts_count_dist['2-3'] += 1
        elif count <= 5:
            fts_count_dist['4-5'] += 1
        elif count <= 10:
            fts_count_dist['6-10'] += 1
        else:
            fts_count_dist['11+'] += 1
    
    for key in sorted(fts_count_dist.keys(), key=lambda x: {'0': 0, '1': 1, '2-3': 2, '4-5': 3, '6-10': 4, '11+': 5}.get(x, 99)):
        print(f"   {key} candidates: {fts_count_dist[key]} ({fts_count_dist[key]/total*100:.1f}%)")
    
    print(f"\n3. CASES WHERE VECTOR RAN - FTS STATS:")
    if vector_cases_fts_stats:
        zero_fts = sum(1 for s in vector_cases_fts_stats if s['fts_candidate_count'] == 0)
        one_fts = sum(1 for s in vector_cases_fts_stats if s['fts_candidate_count'] == 1)
        two_three_fts = sum(1 for s in vector_cases_fts_stats if 2 <= s['fts_candidate_count'] <= 3)
        four_five_fts = sum(1 for s in vector_cases_fts_stats if 4 <= s['fts_candidate_count'] <= 5)
        six_plus_fts = sum(1 for s in vector_cases_fts_stats if s['fts_candidate_count'] >= 6)
        
        print(f"   Total vector cases: {len(vector_cases_fts_stats)}")
        print(f"   0 FTS candidates: {zero_fts} ({zero_fts/len(vector_cases_fts_stats)*100:.1f}%)")
        print(f"   1 FTS candidate: {one_fts} ({one_fts/len(vector_cases_fts_stats)*100:.1f}%)")
        print(f"   2-3 FTS candidates: {two_three_fts} ({two_three_fts/len(vector_cases_fts_stats)*100:.1f}%)")
        print(f"   4-5 FTS candidates: {four_five_fts} ({four_five_fts/len(vector_cases_fts_stats)*100:.1f}%)")
        print(f"   6+ FTS candidates: {six_plus_fts} ({six_plus_fts/len(vector_cases_fts_stats)*100:.1f}%)")
        
        # Show cases with 1+ FTS candidates that still went to vector
        potential_fast_path = [s for s in vector_cases_fts_stats if s['fts_candidate_count'] >= 1]
        print(f"\n   Potential fast-path cases (1+ FTS but vector ran): {len(potential_fast_path)}")
        print(f"   These cases could have used FTS-only if thresholds were lower")
    
    print(f"\n4. RETRIEVAL STAGE BREAKDOWN:")
    stage_dist = defaultdict(int)
    for case in all_case_stats:
        stage_dist[case['retrieval_stage']] += 1
    for stage, count in sorted(stage_dist.items(), key=lambda x: x[1], reverse=True):
        print(f"   {stage}: {count} ({count/total*100:.1f}%)")
    
    print(f"\n5. FTS-ONLY CASES - CANDIDATE COUNT:")
    fts_only_cases = [c for c in all_case_stats if c['fts_only']]
    if fts_only_cases:
        fts_only_counts = [c['fts_candidate_count'] for c in fts_only_cases]
        if fts_only_counts:
            print(f"   Min: {min(fts_only_counts)}")
            print(f"   Max: {max(fts_only_counts)}")
            print(f"   Mean: {sum(fts_only_counts)/len(fts_only_counts):.1f}")
        print(f"   Distribution:")
        fts_only_dist = defaultdict(int)
        for count in fts_only_counts:
            if count == 1:
                fts_only_dist['1'] += 1
            elif count <= 3:
                fts_only_dist['2-3'] += 1
            elif count <= 5:
                fts_only_dist['4-5'] += 1
            else:
                fts_only_dist['6+'] += 1
        for key in sorted(fts_only_dist.keys()):
            print(f"     {key}: {fts_only_dist[key]} ({fts_only_dist[key]/len(fts_only_cases)*100:.1f}%)")
    
    # Show sample queries for different scenarios
    print(f"\n6. SAMPLE QUERIES - FTS-ONLY CASES:")
    for i, case in enumerate(fts_only_cases[:5], 1):
        print(f"   {i}. [{case['fts_candidate_count']} candidates] \"{case['query'][:70]}\"")
    
    print(f"\n7. SAMPLE QUERIES - VECTOR CASES WITH FTS CANDIDATES:")
    vector_with_fts = [c for c in all_case_stats if c['vector_ran'] and c['fts_candidate_count'] > 0]
    for i, case in enumerate(vector_with_fts[:10], 1):
        print(f"   {i}. [{case['fts_candidate_count']} FTS] \"{case['query'][:70]}\" (stage: {case['retrieval_stage']})")
    
    print(f"\n8. SAMPLE QUERIES - VECTOR CASES WITH 0 FTS:")
    vector_no_fts = [c for c in all_case_stats if c['vector_ran'] and c['fts_candidate_count'] == 0]
    for i, case in enumerate(vector_no_fts[:10], 1):
        print(f"   {i}. \"{case['query'][:70]}\" (stage: {case['retrieval_stage']})")
    
    # Recommendation based on data
    print(f"\n" + "=" * 80)
    print("RECOMMENDATIONS FOR FTS-ONLY FAST PATH GATING")
    print("=" * 80)
    
    # Current threshold: fts_candidate_count >= 1 AND (fts_top_score >= 0.12 OR (fts_candidate_count >= 2 AND fts_gap >= 0.03))
    
    potential_fast_path_cases = len([c for c in all_case_stats if c['fts_candidate_count'] >= 1 and not c['fts_only']])
    current_fts_only = len(fts_only_cases)
    
    print(f"\nCurrent performance:")
    print(f"  FTS-only cases: {current_fts_only} ({current_fts_only/total*100:.1f}%)")
    print(f"  Cases with 1+ FTS candidates that went to vector: {potential_fast_path_cases}")
    
    # If we want 30-60% FTS-only, we need to capture more cases
    target_low = int(total * 0.30)
    target_high = int(total * 0.60)
    
    print(f"\nTarget: 30-60% FTS-only ({target_low}-{target_high} cases)")
    
    # Analyze what thresholds would work
    # If we lower to just "1+ candidates", how many would that be?
    would_be_fts_only_if_1plus = len([c for c in all_case_stats if c['fts_candidate_count'] >= 1])
    
    print(f"\nIf threshold = '1+ candidates' (no score check):")
    print(f"  Would trigger: {would_be_fts_only_if_1plus} ({would_be_fts_only_if_1plus/total*100:.1f}%)")
    
    would_be_fts_only_if_2plus = len([c for c in all_case_stats if c['fts_candidate_count'] >= 2])
    print(f"\nIf threshold = '2+ candidates' (no score check):")
    print(f"  Would trigger: {would_be_fts_only_if_2plus} ({would_be_fts_only_if_2plus/total*100:.1f}%)")
    
    print(f"\nRECOMMENDED THRESHOLD (conservative, aiming for ~40%):")
    print(f"  fts_candidate_count >= 1")
    print(f"  (No score check needed - if FTS found at least 1 candidate, trust it)")
    print(f"  Expected result: ~{would_be_fts_only_if_1plus} cases ({would_be_fts_only_if_1plus/total*100:.1f}%)")
    
    print(f"\nALTERNATIVE (if we want more selective, aiming for ~35%):")
    print(f"  fts_candidate_count >= 2")
    print(f"  Expected result: ~{would_be_fts_only_if_2plus} cases ({would_be_fts_only_if_2plus/total*100:.1f}%)")

if __name__ == '__main__':
    json_path = sys.argv[1] if len(sys.argv) > 1 else 'tools/results/confidence_sparkys_electrical_20260110_171832.json'
    analyze_confidence_detailed(json_path)

