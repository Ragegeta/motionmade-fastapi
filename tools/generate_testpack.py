#!/usr/bin/env python3
"""Generate a JSON test pack for a tenant with diverse query patterns."""
import json
import random
import argparse
from pathlib import Path
from typing import List


def add_typos(text: str, typo_rate: float = 0.2) -> str:
    """Add typos to text by swapping letters and removing vowels."""
    words = text.split()
    result = []
    for word in words:
        if random.random() < typo_rate and len(word) > 3:
            # Swap adjacent letters
            if random.random() < 0.5 and len(word) > 4:
                chars = list(word)
                idx = random.randint(0, len(chars) - 2)
                chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
                word = ''.join(chars)
            # Remove a vowel (sometimes)
            elif random.random() < 0.3 and any(v in word.lower() for v in 'aeiou'):
                word = word.replace(random.choice('aeiouAEIOU'), '', 1)
        result.append(word)
    return ' '.join(result)


def add_filler_words(text: str, filler_rate: float = 0.3) -> str:
    """Add filler words to simulate messy speech."""
    fillers = ['um', 'uh', 'hey', 'like', 'you know', 'actually', 'so', 'well']
    words = text.split()
    result = []
    for word in words:
        result.append(word)
        if random.random() < filler_rate and len(words) > 2:
            result.append(random.choice(fillers))
    return ' '.join(result)


def generate_should_hit_queries(seed: int = 123) -> List[str]:
    """Generate should-hit queries across different patterns."""
    random.seed(seed)
    
    queries = []
    
    # Short keyword queries (2-3 words)
    short_keywords = [
        "powerpoint broken",
        "smoke alarm beeping",
        "circuit breaker tripping",
        "outlet sparking",
        "lights flickering",
        "safety switch trips",
        "power point not working",
        "wall socket hot",
        "fuse box humming",
        "switchboard upgrade",
        "ceiling fan install",
        "downlights kitchen",
        "RCD keeps tripping",
        "power outage garage",
        "socket replacement",
        "light switch broken",
        "electrical fault",
        "voltage drop",
        "smoke detector battery",
        "hot outlet danger"
    ]
    queries.extend(short_keywords)
    
    # Normal sentence queries
    normal_sentences = [
        "my powerpoint stopped working can you fix it",
        "sparks coming from wall socket",
        "lights dimming when ac turns on",
        "circuit breaker keeps flipping",
        "smoke alarm beeping every few minutes",
        "safety switch tripping constantly",
        "power went out in half the house",
        "outlet feels hot to touch",
        "need more power points in lounge room",
        "power keeps cutting out in garage",
        "lights flicker when washing machine runs",
        "fuse box making humming noise",
        "need extra sockets in office",
        "smoke detector chirping at night",
        "safety switch trips when i use dryer",
        "how much to replace old switchboard",
        "wall plug not working anymore",
        "that beeping sound is driving me crazy",
        "smoke alarm chirping nonstop",
        "lights flicker when i turn on appliances",
        "safety switch trips every time",
        "smoke detector battery low",
        "safety switch won't reset",
        "smoke alarm false alarms",
        "powerpoint making buzzing noise",
        "outlet sparking when i plug things in",
        "lights dim when i use the dryer",
        "ceiling fan stopped working",
        "switchboard making weird noises",
        "power went out completely",
        "electrical panel needs upgrade",
        "fire alarm battery replacement",
        "rcd keeps tripping what should i do",
        "electrical outlet not working",
        "need new lights installed"
    ]
    queries.extend(normal_sentences)
    
    # Messy speech queries (with fillers)
    messy_base = [
        "my powerpoint stopped working",
        "smoke alarm beeping",
        "circuit breaker tripping",
        "outlet sparking",
        "lights flickering",
        "safety switch trips",
        "need more power points",
        "power keeps cutting out",
        "smoke detector chirping",
        "outlet feels hot"
    ]
    for base in messy_base:
        messy = add_filler_words(base, filler_rate=0.4)
        queries.append(messy)
    
    # Typo queries
    typo_base = [
        "powerpoint stopped working",
        "smoke alarm beeping",
        "circuit breaker tripping",
        "outlet sparking",
        "lights flickering",
        "safety switch trips",
        "wall socket hot",
        "fuse box humming",
        "switchboard upgrade",
        "ceiling fan install"
    ]
    for base in typo_base:
        typo = add_typos(base, typo_rate=0.3)
        queries.append(typo)
    
    # Aussie phrasing queries
    aussie_queries = [
        "power point not working",
        "safety switch keeps tripping",
        "rcd won't stay on",
        "switchboard making crackling sounds",
        "gpo stopped working",
        "rcd keeps tripping what should i do",
        "power point making buzzing noise",
        "safety switch won't reset",
        "need more power points installed",
        "wall plug needs replacing",
        "gpo not working anymore",
        "rcd tripping constantly",
        "safety switch issues",
        "power point upgrade needed"
    ]
    queries.extend(aussie_queries)
    
    # Emergency phrasing queries
    emergency_queries = [
        "sparks coming from outlet",
        "burning smell from switchboard",
        "hot outlet dangerous",
        "outlet smoking",
        "sparks when i plug in",
        "smoke coming from outlet",
        "outlet feels burning hot",
        "sparks from wall socket",
        "burning smell near fuse box",
        "hot power point sparking",
        "urgent electrical fault",
        "sparks and smoke from outlet",
        "outlet burning hot touch",
        "dangerous sparking outlet",
        "burning smell electrical panel"
    ]
    queries.extend(emergency_queries)
    
    # Pricing intent queries
    pricing_queries = [
        "how much for ceiling fan install",
        "how much do you charge",
        "what's your callout fee",
        "how much for new powerpoint",
        "quote for downlights",
        "how much to replace switchboard",
        "what do you charge per hour",
        "callout fee pricing",
        "how much for electrical work",
        "quote please for outlet install",
        "pricing for new lights",
        "how much to install power point",
        "callout fee cost",
        "rate for electrical service",
        "how much for safety switch install"
    ]
    queries.extend(pricing_queries)
    
    # Deduplicate while preserving order
    seen = set()
    unique_queries = []
    for q in queries:
        q_lower = q.lower().strip()
        if q_lower not in seen and len(q_lower) > 0:
            seen.add(q_lower)
            unique_queries.append(q.strip())
    
    return unique_queries


def generate_should_miss_queries(seed: int = 123) -> List[str]:
    """Generate should-miss queries (wrong service)."""
    random.seed(seed + 1000)  # Different seed offset
    
    queries = []
    
    # Plumbing queries
    plumbing_queries = [
        "toilet won't stop running need a plumber",
        "toilet keeps running",
        "blocked drain need plumber",
        "leaking tap needs fixing",
        "hot water system not working",
        "toilet blocked plumber needed",
        "water heater broken",
        "drain blocked urgent",
        "leaking pipe under house",
        "toilet overflowing help",
        "tap dripping constantly",
        "no hot water",
        "plumber needed for leak",
        "toilet repair needed",
        "blocked sink drain"
    ]
    queries.extend(plumbing_queries)
    
    # Locksmith queries
    locksmith_queries = [
        "locked out of house need locksmith",
        "lost keys need locksmith",
        "lock broken can't get in",
        "need locksmith urgent",
        "door lock not working",
        "keys stuck in lock",
        "lock mechanism broken",
        "need new locks installed",
        "emergency locksmith needed",
        "deadbolt not working"
    ]
    queries.extend(locksmith_queries)
    
    # HVAC queries (non-electrical)
    hvac_queries = [
        "gas stove not lighting properly",
        "air conditioner not cooling",
        "heating not working",
        "split system not heating",
        "air con needs repair",
        "duct cleaning needed",
        "heater won't turn on",
        "air conditioner broken",
        "gas heater not working",
        "hvac system repair",
        "cooling system broken",
        "air conditioner maintenance",
        "gas stove repair needed"
    ]
    queries.extend(hvac_queries)
    
    # Solar queries
    solar_queries = [
        "solar panels not generating enough power",
        "solar system not working",
        "solar inverter broken",
        "solar panels need cleaning",
        "solar installation quote",
        "solar system repair",
        "solar panels not charging",
        "solar inverter replacement"
    ]
    queries.extend(solar_queries)
    
    # Other wrong services
    other_wrong = [
        "need a painter for house",
        "roofing repair needed",
        "carpenter needed for deck",
        "tiler needed for bathroom",
        "concrete driveway needed",
        "fencing repair urgent",
        "garden landscaping needed",
        "tree removal service"
    ]
    queries.extend(other_wrong)
    
    # Deduplicate
    seen = set()
    unique_queries = []
    for q in queries:
        q_lower = q.lower().strip()
        if q_lower not in seen and len(q_lower) > 0:
            seen.add(q_lower)
            unique_queries.append(q.strip())
    
    return unique_queries


def generate_edge_unclear_queries(seed: int = 123) -> List[str]:
    """Generate edge/unclear queries (ambiguous cases)."""
    random.seed(seed + 2000)  # Different seed offset
    
    queries = [
        "can you help",
        "what services do you offer",
        "do you service logan",
        "when can you come",
        "are you available",
        "what do you do",
        "services",
        "help",
        "information",
        "booking"
    ]
    
    # Deduplicate
    seen = set()
    unique_queries = []
    for q in queries:
        q_lower = q.lower().strip()
        if q_lower not in seen and len(q_lower) > 0:
            seen.add(q_lower)
            unique_queries.append(q.strip())
    
    return unique_queries


def generate_testpack(tenant: str, seed: int = 123) -> dict:
    """Generate a complete test pack for a tenant."""
    should_hit = generate_should_hit_queries(seed)
    should_miss = generate_should_miss_queries(seed)
    edge_unclear = generate_edge_unclear_queries(seed)
    
    total_queries = len(should_hit) + len(should_miss) + len(edge_unclear)
    
    return {
        "name": f"{tenant.title()} Generated Test Pack",
        "description": f"Generated test pack with {total_queries} queries (seed={seed})",
        "should_hit": should_hit,
        "should_miss": should_miss,
        "edge_unclear": edge_unclear
    }


def main():
    parser = argparse.ArgumentParser(description="Generate a JSON test pack for a tenant")
    parser.add_argument("--tenant", required=True, help="Tenant ID (e.g., sparkys_electrical)")
    parser.add_argument("--out", required=True, help="Output JSON file path")
    parser.add_argument("--seed", type=int, default=123, help="Random seed for reproducibility (default: 123)")
    
    args = parser.parse_args()
    
    # Generate test pack
    testpack = generate_testpack(args.tenant, seed=args.seed)
    
    # Ensure output directory exists
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write JSON file
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(testpack, f, indent=2, ensure_ascii=False)
    
    # Print summary
    total = len(testpack["should_hit"]) + len(testpack["should_miss"]) + len(testpack["edge_unclear"])
    print(f"Generated test pack: {args.out}")
    print(f"  Tenant: {args.tenant}")
    print(f"  Seed: {args.seed}")
    print(f"  Total queries: {total}")
    print(f"    should_hit: {len(testpack['should_hit'])}")
    print(f"    should_miss: {len(testpack['should_miss'])}")
    print(f"    edge_unclear: {len(testpack['edge_unclear'])}")


if __name__ == "__main__":
    main()

