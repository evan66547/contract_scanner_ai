.PHONY: smoke live-check verify

smoke:
	$(if $(wildcard .venv/bin/python3),.venv/bin/python3,python3) scripts/smoke_regression.py

live-check:
	$(if $(wildcard .venv/bin/python3),.venv/bin/python3,python3) scripts/live_ocr_check.py

verify: smoke live-check
