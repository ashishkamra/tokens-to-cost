.PHONY: sync-prices update-prices test serve

sync-prices:
	cp prices.json docs/prices.json
	@echo "docs/prices.json updated"

update-prices:
	python3 tokens_to_cost.py --update-prices
	$(MAKE) sync-prices

test:
	python3 tokens_to_cost.py --show-prices
	@echo ""
	python3 tokens_to_cost.py example.csv
	@echo ""
	python3 tokens_to_cost.py example.csv --json > /dev/null && echo "JSON output: OK"

serve:
	@echo "Open http://localhost:8000 in your browser"
	python3 -m http.server -d docs 8000
