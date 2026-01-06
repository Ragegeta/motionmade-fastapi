"""Test variant expansion locally."""
from app.variant_expander import generate_variants, expand_faq_list

print("=== Testing Variant Expansion ===\n")

# Test smoke alarm FAQ
print("1. Smoke alarm FAQ:")
variants = generate_variants(
    'Smoke alarm installation and service',
    'We install and service smoke alarms. We can fix beeping alarms and replace batteries.'
)
print(f"   Generated {len(variants)} variants")
print("   First 15 variants:")
for v in variants[:15]:
    print(f"     - {v}")
print()

# Test lighting FAQ
print("2. Lighting FAQ:")
variants = generate_variants(
    'Lighting installation',
    'We install all types of lighting including LED downlights, pendant lights, and outdoor lighting.'
)
print(f"   Generated {len(variants)} variants")
print("   First 15 variants:")
for v in variants[:15]:
    print(f"     - {v}")
print()

# Test safety switch FAQ
print("3. Safety switch FAQ:")
variants = generate_variants(
    'Safety switch installation',
    'We install and repair safety switches. If your safety switch keeps tripping, we can help.'
)
print(f"   Generated {len(variants)} variants")
print("   First 15 variants:")
for v in variants[:15]:
    print(f"     - {v}")

