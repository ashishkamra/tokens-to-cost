# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A hackathon token cost calculator that converts per-model token counts (input, output, reasoning, cached) into USD costs. Two interfaces: a Python CLI (`tokens_to_cost.py`) and a static web UI (`docs/`).

## Commands

```bash
# Run cost calculation
python3 tokens_to_cost.py input.csv
python3 tokens_to_cost.py input.csv --format json
python3 tokens_to_cost.py input.csv --format csv

# View available models and prices
python3 tokens_to_cost.py --show-prices
python3 tokens_to_cost.py --list-models

# Update prices from OpenRouter API then sync to web UI
make update-prices

# Sync prices.json to docs/ without fetching
make sync-prices

# Serve web UI locally
make serve
```

## Architecture

- **Single-file CLI** (`tokens_to_cost.py`): CSV parsing, model resolution, cost calculation, output formatting. All prices are USD per 1M tokens (the `SCALE` constant).
- **Static web UI** (`docs/`): Standalone HTML/CSS/JS that loads `docs/prices.json` at runtime. The JS mirrors the Python calculation logic exactly — changes to cost formulas must be made in both `tokens_to_cost.py` and `docs/app.js`.
- **Model resolution**: exact match in `prices.json`, then exact match in `aliases.json`. No fuzzy matching.
- **Price data**: `prices.json` is the source of truth. `docs/prices.json` is a copy synced via `make sync-prices`. Aliases in the web UI are hardcoded in `app.js` and must be kept in sync with `aliases.json`.

## CSV Format

Required columns: `participant`, `model`, `input_tokens`, `output_tokens`, `reasoning_tokens`, `cached_input_tokens`

## Dependencies

Python: `requests`, `tabulate` (see `requirements.txt`). Web UI has no dependencies.
