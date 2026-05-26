.PHONY: smoke

smoke:
	$(if $(wildcard .venv/bin/python3),.venv/bin/python3,python3) scripts/smoke_regression.py
