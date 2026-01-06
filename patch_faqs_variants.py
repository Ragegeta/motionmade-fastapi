#!/usr/bin/env python3
"""Patch FAQs with worst-miss variants."""

import json
from pathlib import Path

# Load current FAQs
faqs_path = Path('tenants/biz9_real/faqs_variants.json')
if not faqs_path.exists():
    faqs_path = Path('tenants/biz9_real/faqs.json')

with open(faqs_path, 'r', encoding='utf-8') as f:
    faqs = json.load(f)

# Variants to add by keyword match in question
patches = {
    'pricing': [
        'cost', 'prices', 'pricing', 'how much', 'quote', 'rates',
        'wat r ur prices', 'ur prices', 'ur prices pls', 'how much u charge',
        'wat do u charge', 'wats the cost', 'price estimate', 'rough cost'
    ],
    'service': [
        'what services do you offer', 'what services', 'services offered',
        'do you clean ovens', 'clean ovens', 'oven cleaning', 'oven',
        'do you do carpets', 'carpet cleaning', 'carpets', 'carpet',
        'what do you do', 'wat do u do', 'do u do deep cleans',
        'deep clean', 'deep cleaning', 'bond clean', 'end of lease',
        'regular clean', 'standard clean'
    ],
    'area': [
        'what areas do you cover', 'wat areas do u cover', 'areas you cover',
        'where do you service', 'service area', 'areas', 'suburbs',
        'do you come to brisbane', 'brisbane', 'do you come to',
        'do u service my area', 'wat areas'
    ],
    'book': [
        'how do i book', 'how to book', 'book', 'booking', 'make a booking',
        'can you come today', 'can u come today', 'can u come 2day', 'come today',
        'today', 'tomorrow', 'can you come tomorrow', 'can u come 2moro',
        'tomorrow arvo', '2moro arvo', 'this arvo', 'arvo',
        'availability', 'availability this week', 'when available',
        'next available', 'soonest', 'schedule', 'appointment'
    ],
    'insur': [
        'are you insured', 'insured', 'insurance', 'do you have insurance',
        'r u insured', 'public liability', 'covered'
    ],
    'cancel': [
        'cancellation policy', 'cancellation', 'cancel', 'can i cancel',
        'reschedule', 'change booking'
    ],
}

# Apply patches
for faq in faqs:
    q_lower = faq.get('question', '').lower()
    current_variants = set(v.lower() for v in faq.get('variants', []))
    
    for keyword, new_variants in patches.items():
        if keyword in q_lower:
            for v in new_variants:
                current_variants.add(v.lower())
    
    faq['variants'] = sorted(list(current_variants))

# Save patched version
output_path = Path('tenants/biz9_real/faqs_patched.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(faqs, f, indent=2, ensure_ascii=False)

# Count
total_variants = sum(len(f.get('variants', [])) for f in faqs)
print(f'Patched {len(faqs)} FAQs with {total_variants} total variants')
print(f'Saved to: {output_path}')


