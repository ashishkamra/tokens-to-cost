# Hackathon Token Cost Calculator

Converts per-model token counts into USD costs for comparing hackathon participant LLM usage. Supports input, output, reasoning, and cached input tokens with per-model pricing.

## Quick Start

```bash
pip install -r requirements.txt
python3 tokens_to_cost.py usage.csv
```

### Example CSV

```csv
participant,model,input_tokens,output_tokens,reasoning_tokens,cached_input_tokens
alice,o3,15000,3000,195000,0
bob,claude-sonnet-4,25000,8000,0,12000
```

### Example Output

```
=== Summary (sorted by total cost) ===

  Rank  Participant      Total Cost  Dominant Cost
     1  bob              $0.1370     output (47%)
     2  alice            $1.5900     reasoning (98%)
```

## Usage

```bash
# Table output (default)
python3 tokens_to_cost.py usage.csv

# JSON or CSV output
python3 tokens_to_cost.py usage.csv --format json
python3 tokens_to_cost.py usage.csv --format csv

# View price table
python3 tokens_to_cost.py --show-prices

# List available model IDs
python3 tokens_to_cost.py --list-models
```

## Web UI

A static web interface is available in `docs/`. It runs entirely in the browser with no backend.

```bash
make serve
# Open http://localhost:8000
```

Paste CSV data or upload a file, then click "Calculate Costs."

## Model Resolution

Models are resolved by exact match against `prices.json`, then against `aliases.json`. Short names like `o3`, `claude-sonnet-4`, and `gemini-2.5-pro` are supported as aliases.

To add a model alias, edit `aliases.json`.

## Updating Prices

Prices are sourced from provider pricing pages and the OpenRouter API. To fetch the latest:

```bash
make update-prices
```

This fetches from the OpenRouter API, merges into `prices.json`, and syncs to `docs/prices.json`.

## Price Format

All prices in `prices.json` are in USD per 1M tokens. Each model entry has:

| Field | Description |
|-------|-------------|
| `input` | Price per 1M input tokens |
| `output` | Price per 1M output tokens |
| `reasoning` | Price per 1M reasoning tokens (null if not applicable) |
| `cached_input` | Price per 1M cached input tokens |
