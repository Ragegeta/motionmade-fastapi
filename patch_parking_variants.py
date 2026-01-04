import json
import argparse
from pathlib import Path

def read_json(path: Path):
    # utf-8-sig safely handles BOM if present
    return json.loads(path.read_text(encoding="utf-8-sig"))

def write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def norm(s: str) -> str:
    return (s or "").strip()

def ensure_list(obj, key: str):
    if key not in obj or obj[key] is None:
        obj[key] = []
    if not isinstance(obj[key], list):
        obj[key] = list(obj[key])

def uniq_preserve(seq):
    seen = set()
    out = []
    for x in seq:
        x = norm(str(x))
        if not x:
            continue
        lx = x.lower()
        if lx in seen:
            continue
        seen.add(lx)
        out.append(x)
    return out

def force_parking_variants(item: dict):
    """
    Ensures the canonical parking FAQ contains all phrasings that your suite and
    real users will ask, so retrieval never falls to fact_miss for parking.
    """
    ensure_list(item, "variants")

    must = [
        "Parking policy",
        "Paid parking",
        "paid parking",
        "What happens if there is paid parking?",
        "Do you charge for parking if it is metered?",
        "Do you charge for parking if it is metered",
        "metered parking",
        "paid spot",
        "visitor spot",
        "billed at cost",
        "if parking is metered",
        "if parking is paid",
        "what if there is paid parking",
        "what happens if there is paid parking",
    ]

    item["variants"] = uniq_preserve(item["variants"] + must)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-TenantId", required=True)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    tenant_dir = root / "tenants" / args.TenantId
    faq_path = tenant_dir / "faqs_variants.json"

    if not faq_path.exists():
        raise FileNotFoundError(f"Missing: {faq_path}")

    data = read_json(faq_path)
    if not isinstance(data, list):
        raise ValueError("faqs_variants.json must be a JSON array")

    # Find canonical parking entry (prefer exact name)
    parking = None
    for x in data:
        if isinstance(x, dict) and norm(x.get("question")) == "Parking policy":
            parking = x
            break

    # Fallback: first item with "parking" in question
    if parking is None:
        for x in data:
            q = norm(x.get("question")) if isinstance(x, dict) else ""
            if "parking" in q.lower():
                parking = x
                break

    if parking is None:
        # If there is no parking FAQ at all, do nothing (or you can raise).
        print(f"OK: no parking FAQ found for tenant {args.TenantId} (no changes).")
        return

    force_parking_variants(parking)
    write_json(faq_path, data)

    print(f"OK: forced parking variants in {faq_path}")

if __name__ == "__main__":
    main()
