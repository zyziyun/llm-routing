# Top-level convenience targets spanning both packages.

.PHONY: test eval gateway-serve edge-dev

test:
	cd packages/gateway && PYTHONPATH=src python3 -m pytest -q
	cd packages/edge-client && node --test

eval:
	cd packages/gateway && PYTHONPATH=src python3 eval/run_eval.py
	cd packages/edge-client && node eval/run-eval.ts

gateway-serve:
	cd packages/gateway && PYTHONPATH=src uvicorn gateway.app:app --port 8000

edge-dev:
	cd packages/edge-client && npm run dev
