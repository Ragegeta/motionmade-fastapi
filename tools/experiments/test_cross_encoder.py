"""Test cross-encoder model loading and scoring."""
from app.cross_encoder import SELF_HOSTED_AVAILABLE, CROSS_ENCODER_MODEL

print("SELF_HOSTED_AVAILABLE:", SELF_HOSTED_AVAILABLE)
print("CROSS_ENCODER_MODEL:", CROSS_ENCODER_MODEL is not None)

if SELF_HOSTED_AVAILABLE and CROSS_ENCODER_MODEL:
    print("[OK] Cross-encoder model loaded")
    # Quick test
    scores = CROSS_ENCODER_MODEL.predict([
        ('are you licensed', 'We are fully licensed and insured electricians'),
        ('do you do plumbing', 'We handle electrical work: powerpoints, lighting'),
    ])
    print(f'   "are you licensed" vs electrical FAQ: {scores[0]:.3f}')
    print(f'   "do you do plumbing" vs electrical FAQ: {scores[1]:.3f}')
    print(f'   Difference: {scores[0] - scores[1]:.3f} (should be positive)')
else:
    print("⚠️ Cross-encoder not available, will use Cohere API")

