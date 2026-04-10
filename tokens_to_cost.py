#!/usr/bin/env python3
"""Hackathon Token Cost Calculator.

Converts per-model token counts into dollar costs for comparing
hackathon participant LLM usage.
"""

import argparse
import csv
import json
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import requests
from tabulate import tabulate

# All prices in prices.json are USD per 1M tokens. This constant is used
# in exactly one place (compute_cost) to convert token counts to dollars.
SCALE = 1_000_000

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PRICES_PATH = SCRIPT_DIR / "prices.json"
DEFAULT_ALIASES_PATH = SCRIPT_DIR / "aliases.json"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"

REQUIRED_CSV_COLUMNS = [
    "participant",
    "model",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_prices(path: Path) -> dict:
    """Load and validate prices.json."""
    with open(path) as f:
        data = json.load(f)
    if "models" not in data:
        print(f"Error: {path} missing 'models' key", file=sys.stderr)
        sys.exit(1)
    return data


def load_aliases(path: Path) -> dict:
    """Load aliases.json."""
    with open(path) as f:
        data = json.load(f)
    if "aliases" not in data:
        print(f"Error: {path} missing 'aliases' key", file=sys.stderr)
        sys.exit(1)
    return data["aliases"]


# ---------------------------------------------------------------------------
# Model resolution — exact match only, no fuzzy matching
# ---------------------------------------------------------------------------

def resolve_model(raw_name: str, prices: dict, aliases: dict) -> str:
    """Resolve a model name to a canonical ID in prices.json.

    Resolution order:
      1. Exact match in prices.json models
      2. Exact match in aliases.json
      3. Error with list of available models
    """
    normalized = raw_name.strip().lower()
    models = prices["models"]

    # 1. Exact match in prices
    if normalized in models:
        return normalized

    # 2. Check aliases
    if normalized in aliases:
        canonical = aliases[normalized]
        if canonical in models:
            return canonical
        print(
            f"Warning: alias '{raw_name}' maps to '{canonical}' "
            f"which is not in prices.json",
            file=sys.stderr,
        )

    # 3. Fail loudly
    available = sorted(models.keys())
    print(
        f"Error: Unknown model '{raw_name}'\n"
        f"  Not found in prices.json or aliases.json.\n"
        f"  Available models: {', '.join(available)}\n"
        f"  Add an alias in aliases.json if this is a known model "
        f"under a different name.",
        file=sys.stderr,
    )
    return None


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_csv(path: str) -> list[dict]:
    """Parse input CSV, validate columns, return list of row dicts."""
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("Error: CSV file is empty", file=sys.stderr)
            sys.exit(1)

        headers = [h.strip().lower() for h in reader.fieldnames]
        missing = [c for c in REQUIRED_CSV_COLUMNS if c not in headers]
        if missing:
            print(
                f"Error: CSV missing required columns: {', '.join(missing)}\n"
                f"  Required: {', '.join(REQUIRED_CSV_COLUMNS)}",
                file=sys.stderr,
            )
            sys.exit(1)

        for i, raw_row in enumerate(reader, start=2):
            # Normalize keys
            row = {k.strip().lower(): v.strip() for k, v in raw_row.items()}
            try:
                rows.append({
                    "participant": row["participant"],
                    "model": row["model"],
                    "input_tokens": int(row["input_tokens"]),
                    "output_tokens": int(row["output_tokens"]),
                    "reasoning_tokens": int(row["reasoning_tokens"]),
                    "cached_input_tokens": int(row["cached_input_tokens"]),
                })
            except (ValueError, KeyError) as e:
                print(f"Error: CSV row {i}: {e}", file=sys.stderr)
                sys.exit(1)
    return rows


# ---------------------------------------------------------------------------
# Cost calculation
# ---------------------------------------------------------------------------

def compute_cost(row: dict, model_prices: dict) -> dict:
    """Compute cost breakdown for a single row.

    All prices are USD per 1M tokens. All token counts are integers.
    """
    input_cost = row["input_tokens"] * model_prices["input"] / SCALE
    output_cost = row["output_tokens"] * model_prices["output"] / SCALE

    # Reasoning tokens
    reasoning_price = model_prices.get("reasoning")
    if reasoning_price is None:
        if row["reasoning_tokens"] > 0:
            warnings.warn(
                f"Model {row['resolved_model']} has no reasoning price; "
                f"using output price for {row['reasoning_tokens']} reasoning tokens"
            )
            reasoning_price = model_prices["output"]
        else:
            reasoning_price = 0
    reasoning_cost = row["reasoning_tokens"] * reasoning_price / SCALE

    # Cached input tokens
    cached_price = model_prices.get("cached_input", model_prices["input"])
    cached_cost = row["cached_input_tokens"] * cached_price / SCALE

    total = input_cost + output_cost + reasoning_cost + cached_cost

    return {
        "participant": row["participant"],
        "model_input": row["model"],
        "model": row["resolved_model"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "reasoning_tokens": row["reasoning_tokens"],
        "cached_input_tokens": row["cached_input_tokens"],
        "input_cost": input_cost,
        "output_cost": output_cost,
        "reasoning_cost": reasoning_cost,
        "cached_input_cost": cached_cost,
        "total_cost": total,
    }


def aggregate_results(costs: list[dict]) -> dict:
    """Group costs by participant, compute totals, sort by total cost."""
    participants = defaultdict(lambda: {"rows": [], "totals": defaultdict(float)})

    for c in costs:
        key = c["participant"].strip().lower()
        display_name = c["participant"]
        p = participants[key]
        if not p["rows"]:
            p["display_name"] = display_name
        p["rows"].append(c)
        for field in ["input_cost", "output_cost", "reasoning_cost",
                       "cached_input_cost", "total_cost",
                       "input_tokens", "output_tokens",
                       "reasoning_tokens", "cached_input_tokens"]:
            p["totals"][field] += c[field]

    # Sort by total cost ascending
    sorted_participants = sorted(
        participants.values(), key=lambda p: p["totals"]["total_cost"]
    )
    return sorted_participants


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_dollar(val: float) -> str:
    """Format a dollar value for display."""
    if val == 0:
        return "$0.000"
    if val < 0.001:
        return f"${val:.6f}"
    if val < 1:
        return f"${val:.4f}"
    return f"${val:.2f}"


def dominant_cost_type(totals: dict) -> str:
    """Return which cost type dominates for a participant."""
    total = totals["total_cost"]
    if total == 0:
        return "n/a"
    costs = {
        "input": totals["input_cost"],
        "output": totals["output_cost"],
        "reasoning": totals["reasoning_cost"],
        "cached": totals["cached_input_cost"],
    }
    top_type = max(costs, key=costs.get)
    pct = costs[top_type] / total * 100
    return f"{top_type} ({pct:.0f}%)"


def print_table(results: list[dict]) -> None:
    """Print formatted cost breakdown tables."""
    print("=== Cost Breakdown ===\n")

    for p in results:
        name = p["display_name"]
        print(f"Participant: {name}")
        table_data = []
        for r in p["rows"]:
            table_data.append([
                r["model"],
                f"{r['input_tokens']:,}",
                f"{r['output_tokens']:,}",
                f"{r['reasoning_tokens']:,}",
                f"{r['cached_input_tokens']:,}",
                format_dollar(r["input_cost"]),
                format_dollar(r["output_cost"]),
                format_dollar(r["reasoning_cost"]),
                format_dollar(r["cached_input_cost"]),
                format_dollar(r["total_cost"]),
            ])

        t = p["totals"]
        table_data.append([
            "TOTAL",
            f"{int(t['input_tokens']):,}",
            f"{int(t['output_tokens']):,}",
            f"{int(t['reasoning_tokens']):,}",
            f"{int(t['cached_input_tokens']):,}",
            format_dollar(t["input_cost"]),
            format_dollar(t["output_cost"]),
            format_dollar(t["reasoning_cost"]),
            format_dollar(t["cached_input_cost"]),
            format_dollar(t["total_cost"]),
        ])

        headers = [
            "Model", "Input Tok", "Output Tok", "Reason Tok", "Cached Tok",
            "Input$", "Output$", "Reason$", "Cached$", "Total$",
        ]
        print(tabulate(table_data, headers=headers, tablefmt="simple",
                        colalign=("left",) + ("right",) * 9))
        print()

    # Summary
    print("=== Summary (sorted by total cost) ===\n")
    summary_data = []
    for rank, p in enumerate(results, 1):
        summary_data.append([
            rank,
            p["display_name"],
            format_dollar(p["totals"]["total_cost"]),
            dominant_cost_type(p["totals"]),
        ])
    print(tabulate(summary_data,
                    headers=["Rank", "Participant", "Total Cost", "Dominant Cost"],
                    tablefmt="simple",
                    colalign=("right", "left", "right", "left")))
    print()


def print_json_output(results: list[dict]) -> None:
    """Print results as JSON."""
    output = []
    for p in results:
        output.append({
            "participant": p["display_name"],
            "rows": p["rows"],
            "totals": dict(p["totals"]),
        })
    print(json.dumps(output, indent=2))


def print_csv_output(results: list[dict]) -> None:
    """Print results as CSV."""
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=[
            "participant", "model", "input_tokens", "output_tokens",
            "reasoning_tokens", "cached_input_tokens",
            "input_cost", "output_cost", "reasoning_cost",
            "cached_input_cost", "total_cost",
        ],
    )
    writer.writeheader()
    for p in results:
        for r in p["rows"]:
            writer.writerow({
                "participant": r["participant"],
                "model": r["model"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "reasoning_tokens": r["reasoning_tokens"],
                "cached_input_tokens": r["cached_input_tokens"],
                "input_cost": f"{r['input_cost']:.6f}",
                "output_cost": f"{r['output_cost']:.6f}",
                "reasoning_cost": f"{r['reasoning_cost']:.6f}",
                "cached_input_cost": f"{r['cached_input_cost']:.6f}",
                "total_cost": f"{r['total_cost']:.6f}",
            })


def print_prices_table(prices: dict) -> None:
    """Print the prices table (--show-prices)."""
    meta = prices.get("_meta", {})
    print(f"Prices (USD per 1M tokens) — last updated: {meta.get('last_updated', 'unknown')}")
    print(f"Source: {meta.get('source', 'unknown')}\n")

    table_data = []
    for model_id, p in sorted(prices["models"].items()):
        reasoning = format_dollar(p["reasoning"]) if p.get("reasoning") is not None else "—"
        table_data.append([
            model_id,
            format_dollar(p["input"]),
            format_dollar(p["output"]),
            reasoning,
            format_dollar(p.get("cached_input", p["input"])),
        ])

    print(tabulate(table_data,
                    headers=["Model", "Input", "Output", "Reasoning", "Cached Input"],
                    tablefmt="simple",
                    colalign=("left", "right", "right", "right", "right")))


def print_model_list(prices: dict) -> None:
    """Print list of model IDs (--list-models)."""
    for model_id in sorted(prices["models"].keys()):
        print(model_id)


# ---------------------------------------------------------------------------
# Price update from OpenRouter
# ---------------------------------------------------------------------------

def update_prices(prices_path: Path) -> None:
    """Fetch latest prices from OpenRouter API and merge into prices.json."""
    print(f"Fetching models from {OPENROUTER_API_URL}...")
    try:
        resp = requests.get(OPENROUTER_API_URL, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching OpenRouter API: {e}", file=sys.stderr)
        sys.exit(1)

    api_data = resp.json().get("data", [])
    print(f"  Received {len(api_data)} models from OpenRouter")

    # Load existing prices
    prices = load_prices(prices_path)
    existing_models = set(prices["models"].keys())
    added = []
    updated = []

    for model in api_data:
        model_id = model.get("id", "").lower()
        pricing = model.get("pricing", {})

        prompt_str = pricing.get("prompt", "0")
        completion_str = pricing.get("completion", "0")
        reasoning_str = pricing.get("internal_reasoning")
        cached_str = pricing.get("input_cache_read")

        try:
            prompt_per_1m = float(prompt_str) * SCALE
            completion_per_1m = float(completion_str) * SCALE
            reasoning_per_1m = float(reasoning_str) * SCALE if reasoning_str else None
            cached_per_1m = float(cached_str) * SCALE if cached_str else None
        except (ValueError, TypeError):
            continue

        # Skip free models
        if prompt_per_1m == 0 and completion_per_1m == 0:
            continue

        new_entry = {
            "input": round(prompt_per_1m, 4),
            "output": round(completion_per_1m, 4),
            "reasoning": round(reasoning_per_1m, 4) if reasoning_per_1m is not None else None,
            "cached_input": round(cached_per_1m, 4) if cached_per_1m is not None else prompt_per_1m,
            "source": "openrouter",
        }

        if model_id in existing_models:
            existing = prices["models"][model_id]
            # Don't overwrite manually curated entries
            if existing.get("source") != "openrouter" and "source" not in existing:
                continue
            prices["models"][model_id] = new_entry
            updated.append(model_id)
        else:
            prices["models"][model_id] = new_entry
            added.append(model_id)

    # Update metadata
    prices["_meta"]["last_updated"] = "2026-04-10"

    # Write back
    with open(prices_path, "w") as f:
        json.dump(prices, f, indent=2)
        f.write("\n")

    print(f"\nResults:")
    print(f"  Added: {len(added)} new models")
    print(f"  Updated: {len(updated)} existing models")
    if added:
        print(f"  New models: {', '.join(sorted(added)[:10])}")
        if len(added) > 10:
            print(f"    ... and {len(added) - 10} more")
    print(f"\nPrices written to {prices_path}")
    print("Remember to run 'make sync-prices' to update docs/prices.json")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Hackathon Token Cost Calculator — convert token counts to costs"
    )
    parser.add_argument(
        "csv_file", nargs="?",
        help="Path to participant token usage CSV"
    )
    parser.add_argument(
        "--prices", type=Path, default=DEFAULT_PRICES_PATH,
        help=f"Path to prices.json (default: {DEFAULT_PRICES_PATH})"
    )
    parser.add_argument(
        "--aliases", type=Path, default=DEFAULT_ALIASES_PATH,
        help=f"Path to aliases.json (default: {DEFAULT_ALIASES_PATH})"
    )
    parser.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        dest="output_format",
        help="Output format (default: table)"
    )
    parser.add_argument(
        "--json", action="store_const", const="json", dest="output_format",
        help="Shorthand for --format json"
    )
    parser.add_argument(
        "--show-prices", action="store_true",
        help="Display price table and exit"
    )
    parser.add_argument(
        "--list-models", action="store_true",
        help="List available model IDs and exit"
    )
    parser.add_argument(
        "--update-prices", action="store_true",
        help="Fetch latest prices from OpenRouter API and update prices.json"
    )

    args = parser.parse_args()

    # Handle --update-prices
    if args.update_prices:
        update_prices(args.prices)
        return

    # Load prices
    prices = load_prices(args.prices)

    # Handle --show-prices
    if args.show_prices:
        print_prices_table(prices)
        return

    # Handle --list-models
    if args.list_models:
        print_model_list(prices)
        return

    # Need a CSV file for cost calculation
    if not args.csv_file:
        parser.error("csv_file is required for cost calculation")

    # Load aliases and CSV
    aliases = load_aliases(args.aliases)
    rows = parse_csv(args.csv_file)

    if not rows:
        print("No data rows found in CSV", file=sys.stderr)
        sys.exit(1)

    # Resolve models and compute costs
    costs = []
    errors = 0
    for row in rows:
        resolved = resolve_model(row["model"], prices, aliases)
        if resolved is None:
            errors += 1
            continue
        row["resolved_model"] = resolved
        model_prices = prices["models"][resolved]
        costs.append(compute_cost(row, model_prices))

    if errors:
        print(f"\n{errors} row(s) skipped due to unknown models.", file=sys.stderr)

    if not costs:
        print("Error: No valid rows to process", file=sys.stderr)
        sys.exit(1)

    # Aggregate and output
    results = aggregate_results(costs)

    if args.output_format == "json":
        print_json_output(results)
    elif args.output_format == "csv":
        print_csv_output(results)
    else:
        print_table(results)

    # Exit with error code if any models were unresolved
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
