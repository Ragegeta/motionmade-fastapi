"""Verify wrong-service keywords were added correctly."""
from app.retriever import WRONG_SERVICE_KEYWORDS

keywords = WRONG_SERVICE_KEYWORDS
print(f"Total keywords: {len(keywords)}")
print(f"\nNew keywords added:")
print(f"  paint: {'paint' in keywords}")
print(f"  powerpoint: {'powerpoint' in keywords}")
print(f"  'power point': {'power point' in keywords}")
print(f"  socket: {'socket' in keywords}")
print(f"  outlet: {'outlet' in keywords}")
print(f"  switchboard: {'switchboard' in keywords}")
print(f"  wiring: {'wiring' in keywords}")
print(f"  electrician: {'electrician' in keywords}")
print(f"  sparky: {'sparky' in keywords}")

print(f"\nExisting keywords still present:")
print(f"  painting: {'painting' in keywords}")
print(f"  painter: {'painter' in keywords}")


