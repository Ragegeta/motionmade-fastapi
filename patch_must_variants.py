import json, re, argparse
from pathlib import Path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def dedupe(items):
    seen = set()
    out = []
    for x in items or []:
        if not x:
            continue
        k = norm(str(x))
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(str(x).strip())
    return out


def force_front(item, must_list, cap=60):
    base = list(must_list or []) + list(item.get("variants") or [])
    item["variants"] = dedupe(base)[:cap]


def find_by_question(items, qname: str):
    nq = norm(qname)
    for it in items:
        if norm(it.get("question", "")) == nq:
            return it
    return None


def find_by_answer(items, any_needles):
    for it in items:
        a = (it.get("answer") or "").lower()
        for needles in any_needles:
            if all(n.lower() in a for n in needles):
                return it
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--faqfile", required=True)
    ap.add_argument("--profile", required=True)
    args = ap.parse_args()

    faq_path = Path(args.faqfile)
    data = read_json(faq_path)

    profile_path = Path(args.profile)
    prof = read_json(profile_path) if profile_path.exists() else {}

    must = (prof.get("must") or prof.get("must_variants") or {}) or {}

    # normalize profile key variants
    if "pricing" not in must and "pricing_oven" in must:
        must["pricing"] = must["pricing_oven"]

    patched = []

    # PRICING (prefer exact question name if present)
    if must.get("pricing"):
        it = find_by_question(data, "Oven clean add-on")
        if not it:
            it = find_by_answer(data, [["oven", "$"], ["oven", "add-on"], ["oven", "optional"]])
        if it:
            force_front(it, must["pricing"], cap=60)
            patched.append(f"pricing -> {it.get('question')}")

    # SUPPLIES (prefer exact question name)
    if must.get("supplies"):
        it = find_by_question(data, "Supplies and equipment")
        if not it:
            it = find_by_answer(data, [["bring", "supplies"], ["cleaning supplies"], ["bring", "vacuum"]])
        if it:
            force_front(it, must["supplies"], cap=60)
            patched.append(f"supplies -> {it.get('question')}")

    # SERVICE AREA (prefer exact question name)
    if must.get("service_area"):
        it = find_by_question(data, "Service area")
        if not it:
            it = find_by_answer(data, [["service", "brisbane"], ["service", "suburb"], ["cover", "suburb"]])
        if it:
            force_front(it, must["service_area"], cap=60)
            patched.append(f"service_area -> {it.get('question')}")

    write_json(faq_path, data)
    print("patch_must_variants.py: OK")
    if patched:
        print("patched:", "; ".join(patched))
    else:
        print("patched: NONE (check profile must_variants keys)")


if __name__ == "__main__":
    main()
