import argparse, json, re, shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any


STOP_TOKENS = {
    "do","does","did","you","u","ya","i","we","me","my","our","your","ur","a","an","the",
    "is","are","am","can","could","would","will","to","of","in","on","for","and","or",
    "it","this","that","guys"
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9\s\$\?]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items or []:
        if not x:
            continue
        x = str(x).strip()
        k = norm(x)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def merge_aliases(core: Dict[str, List[str]], tenant: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for src in (core or {}, tenant or {}):
        for k, vals in src.items():
            k2 = norm(k)
            if not k2:
                continue
            out.setdefault(k2, [])
            out[k2].extend([norm(v) for v in (vals or []) if norm(v)])
    for k in list(out.keys()):
        out[k] = dedupe_keep_order(out[k])
    return out


def apply_aliases(sentence: str, aliases: Dict[str, List[str]], limit: int = 18) -> List[str]:
    base = norm(sentence)
    toks = base.split()
    if not toks:
        return []

    variants = [toks]
    for i, tok in enumerate(toks):
        if tok in STOP_TOKENS or len(tok) < 4:
            continue
        if tok not in aliases:
            continue

        new = []
        for cur in variants:
            for alt in aliases[tok]:
                if not alt or alt in STOP_TOKENS:
                    continue
                cur2 = cur[:]
                cur2[i] = alt
                new.append(cur2)
        variants.extend(new)
        if len(variants) > 120:
            variants = variants[:120]

    out = []
    seen = set()
    for tks in variants:
        s = " ".join(tks).strip()
        k = norm(s)
        if k and k not in seen:
            seen.add(k)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def expand_templates(templates: List[str], places: List[str], things: List[str]) -> List[str]:
    out = []
    for tpl in templates or []:
        if "{place}" in tpl:
            for p in places or []:
                out.append(tpl.replace("{place}", p))
        elif "{thing}" in tpl:
            for th in things or []:
                out.append(tpl.replace("{thing}", th))
        else:
            out.append(tpl)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--infile", required=True)
    ap.add_argument("--outfile", required=True)
    ap.add_argument("--core", required=True)
    ap.add_argument("--profile", required=True)
    args = ap.parse_args()

    infile = Path(args.infile)
    outfile = Path(args.outfile)
    coref = Path(args.core)
    prof = Path(args.profile)

    data = read_json(infile)
    core = read_json(coref)
    tenant = read_json(prof)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = infile.with_suffix(infile.suffix + f".bak_{ts}")
    shutil.copy2(infile, bak)
    print(f"Backup: {bak.name}")

    max_per = int(core.get("max_variants_per_faq", tenant.get("max_variants_per_faq", 60)))

    aliases = merge_aliases(core.get("aliases", {}), tenant.get("aliases", {}))
    templates = core.get("templates", {}) or {}

    places = tenant.get("places") or tenant.get("service_area_places") or []
    pricing_things = tenant.get("pricing_things", []) or []

    changed = 0
    for item in data:
        q = item.get("question", "") or ""
        existing = item.get("variants") or []

        qn = norm(q)

        generated: List[str] = []

        # CRITICAL: only apply domain templates to the intended FAQ item,
        # otherwise Travel fee competes with Service area and delta collapses.
        if qn == "service area":
            generated.extend(expand_templates(templates.get("service_area", []), places, []))
        elif qn == "supplies and equipment":
            generated.extend(expand_templates(templates.get("supplies", []), [], []))
        elif qn == "oven clean add-on":
            generated.extend(expand_templates(templates.get("pricing", []), [], pricing_things))

        if q:
            generated.append(q)

        expanded: List[str] = []
        for g in generated:
            expanded.extend(apply_aliases(g, aliases, limit=18))

        merged = dedupe_keep_order(existing + generated + expanded)[:max_per]

        if norm(" | ".join(existing)) != norm(" | ".join(merged)):
            item["variants"] = merged
            changed += 1

    write_json(outfile, data)
    print(f"Updated FAQs: {changed}/{len(data)} written to {outfile.name}")


if __name__ == "__main__":
    main()
