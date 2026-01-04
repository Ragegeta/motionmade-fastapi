# Messy Input Benchmark Tool

A simple benchmark runner for testing messy/real-world inputs against the FastAPI quote reply endpoint.

## Quick Start

### Run Locally (No Delay)

```bash
cd tools
python bench_messy_inputs.py --base-url http://localhost:8000 --tenant-id biz9_real
```

### Run Against Production (With Delay)

```bash
cd tools
python bench_messy_inputs.py \
  --base-url https://motionmade-fastapi.onrender.com \
  --tenant-id biz9_real \
  --delay-ms 200
```

The `--delay-ms` flag adds a delay between requests to avoid rate limiting. Use 100-500ms for production.

## Options

- `--base-url`: API base URL (default: `http://localhost:8000`)
- `--tenant-id`: Tenant ID to test (default: `biz9_real`)
- `--cases-file`: Path to test cases JSON (default: `tools/bench_cases.json`)
- `--delay-ms`: Delay between requests in milliseconds (default: `0`)
- `--output-dir`: Directory to save results (default: `tools/`)

## Test Cases

Edit `bench_cases.json` to add/modify test cases. Each case should have:
- `name`: Unique identifier
- `category`: Category (junk, typo, fluff, etc.)
- `input`: The test message

## Output

The tool prints:
- Summary statistics (hits, clarifies, fallbacks, avg latency)
- Worst 5 misses (lowest retrieval scores)
- Saves full results to `bench_results_<timestamp>.json`

## Example Output

```
======================================================================
MESSY INPUT BENCHMARK SUMMARY
======================================================================

Total Cases: 15
FAQ Hits: 8 (53.3%)
Clarifies: 3 (20.0%)
Fallbacks: 2 (13.3%)
Fact Hits: 5
Fact Rewrite Hits: 3
General OK: 2
Avg Latency: 1234.5 ms

----------------------------------------------------------------------
WORST 5 MISSES (Lowest Scores):
----------------------------------------------------------------------
1. Score: 0.6543 | Branch: fact_miss            | Input: wat r ur prces?...
2. Score: 0.7123 | Branch: general_fallback     | Input: hey so basically wat r ur...
3. Score: 0.7234 | Branch: fact_miss            | Input: do u alow pets?...
4. Score: 0.7456 | Branch: fact_miss            | Input: wat r ur prces?...
5. Score: 0.7567 | Branch: general_fallback     | Input: hey quick one - ur prices...

======================================================================
```

## Requirements

- Python 3.8+
- `requests` library: `pip install requests`

## Notes

- The tool does NOT modify production logic
- Results are saved with timestamps for comparison over time
- Use delays when testing production to avoid rate limiting
- All test cases are defined in JSON for easy modification


