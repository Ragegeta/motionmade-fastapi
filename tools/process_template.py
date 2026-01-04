#!/usr/bin/env python3
"""
Process an FAQ template with business-specific values.

Usage:
    python process_template.py <template_id> <output_path> --field=value --field=value

Example:
    python process_template.py cleaning_service tenants/acme/faqs.json \
        --business_name="Acme Cleaning" \
        --service_area="Brisbane metro" \
        --base_price="$150" \
        --phone="0400 123 456" \
        --email="hello@acme.com"
"""

import json
import sys
import re
from pathlib import Path


def load_template(template_id: str) -> dict:
    """Load a template by ID."""
    templates_dir = Path(__file__).parent.parent / "templates" / "faq_templates"
    template_path = templates_dir / f"{template_id}.json"
    
    if not template_path.exists():
        available = [f.stem for f in templates_dir.glob("*.json")]
        raise FileNotFoundError(
            f"Template '{template_id}' not found. Available: {available}"
        )
    
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f)


def fill_template(template: dict, values: dict) -> list:
    """Fill in template placeholders with business values."""
    faqs = []
    
    for faq_template in template["faqs"]:
        answer = faq_template["answer_template"]
        
        # Replace all {{field}} placeholders
        for field, value in values.items():
            answer = answer.replace(f"{{{{{field}}}}}", value)
        
        # Check for unfilled placeholders
        unfilled = re.findall(r'\{\{(\w+)\}\}', answer)
        if unfilled:
            print(f"Warning: FAQ '{faq_template['question']}' has unfilled placeholders: {unfilled}")
        
        faq = {
            "question": faq_template["question"],
            "answer": answer,
            "variants": faq_template["variants"],
            "category": faq_template.get("category", "general"),
            "must_hit": faq_template.get("must_hit", False)
        }
        faqs.append(faq)
    
    return faqs


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    template_id = sys.argv[1]
    output_path = sys.argv[2]
    
    # Parse --field=value arguments
    values = {}
    for arg in sys.argv[3:]:
        if arg.startswith("--") and "=" in arg:
            key, value = arg[2:].split("=", 1)
            values[key] = value
    
    # Load and process template
    template = load_template(template_id)
    
    # Check required fields
    required = [f["field"] for f in template.get("required_fields", [])]
    missing = [f for f in required if f not in values]
    if missing:
        print(f"Error: Missing required fields: {missing}")
        print("\nRequired fields:")
        for f in template["required_fields"]:
            print(f"  --{f['field']}=\"{f['example']}\"  # {f['description']}")
        sys.exit(1)
    
    # Generate FAQs
    faqs = fill_template(template, values)
    
    # Write output
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output, "w", encoding="utf-8") as f:
        json.dump(faqs, f, indent=2, ensure_ascii=False)
    
    print(f"Generated {len(faqs)} FAQs with {sum(len(f['variants']) for f in faqs)} variants")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()

