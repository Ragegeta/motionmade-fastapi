import argparse
import json
import re
from pathlib import Path


def norm(s: str) -> str:
    if s is None:
        return ""
    s = str(s).lower()
    s = re.sub(r"[_\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def dedupe_preserve_order(items):
    seen = set()
    out = []
    for x in items:
        nx = norm(x)
        if not nx:
            continue
        if nx in seen:
            continue
        seen.add(nx)
        out.append(x)
    return out


def find_target_faq(faqs, key: str):
    nk = norm(key)

    for it in faqs:
        if norm(it.get("question", "")) == nk:
            return it, "exact"

    matches = []
    for it in faqs:
        nq = norm(it.get("question", ""))
        if nk and (nk in nq):
            matches.append(it)

    if len(matches) == 1:
        return matches[0], "partial"

    return None, "none"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--faqfile", required=True, help="Path to faqs_variants.json (in-place patched).")
    ap.add_argument("--profile", required=True, help="Path to tenant variant_profile.json.")
    args = ap.parse_args()

    faq_path = Path(args.faqfile)
    prof_path = Path(args.profile)

    faqs = load_json(faq_path)
    prof = load_json(prof_path)

    must = prof.get("must_variants") or {}
    if not isinstance(must, dict):
        raise SystemExit("must_variants must be an object/dict in variant_profile.json")

    patched = []
    skipped = []

    for key, variants in must.items():
        if not isinstance(variants, list) or len(variants) == 0:
            skipped.append((key, "empty_or_not_list"))
            continue

        target, how = find_target_faq(faqs, key)
        if target is None:
            skipped.append((key, "no_matching_faq_question"))
            continue

        existing = target.get("variants") or []
        if not isinstance(existing, list):
            existing = []

        combined = [target.get("question", "")] + existing + variants
        target["variants"] = dedupe_preserve_order(combined)

        patched.append((key, target.get("question", ""), how, len(existing), len(target["variants"])))

    save_json(faq_path, faqs)

    print("patch_must_variants.py: OK")
    for key, q, how, before, after in patched:
        print(f"patched: {key} -> {q} ({how})  variants: {before} -> {after}")

    if skipped:
        print("skipped:")
        for key, reason in skipped:
            print(f"  - {key}: {reason}")


if __name__ == "__main__":
    main()
