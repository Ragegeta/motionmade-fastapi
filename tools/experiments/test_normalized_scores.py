"""Test normalized cross-encoder scores."""
from app.cross_encoder import CROSS_ENCODER_MODEL
import numpy as np

scores = CROSS_ENCODER_MODEL.predict([
    ('are you licensed', 'We are fully licensed and insured electricians'),
    ('do you do plumbing', 'We handle electrical work: powerpoints, lighting'),
])

normalized = 1 / (1 + np.exp(-np.array(scores)))

print(f'Raw scores: {scores}')
print(f'Normalized: {normalized}')
print(f'"are you licensed" vs electrical: {normalized[0]:.3f} (should be > 0.3)')
print(f'"do you do plumbing" vs electrical: {normalized[1]:.3f} (should be < 0.3)')

from app.cross_encoder import should_accept

accept1, reason1 = should_accept(normalized[0])
accept2, reason2 = should_accept(normalized[1])

print(f'\n"are you licensed": accept={accept1}, reason={reason1}')
print(f'"do you do plumbing": accept={accept2}, reason={reason2}')


