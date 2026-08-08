# Top-level convenience targets spanning both packages.

.PHONY: test eval demo gateway-serve edge-dev

test:
	cd packages/gateway && PYTHONPATH=src python3 -m pytest -q
	cd packages/edge-client && node --test

eval:
	cd packages/gateway && PYTHONPATH=src python3 eval/run_eval.py
	cd packages/edge-client && node eval/run-eval.ts

demo:
	cd packages/gateway && PYTHONPATH=src python3 demo/demo.py

gateway-serve:
	cd packages/gateway && PYTHONPATH=src uvicorn gateway.app:app --port 8000

edge-dev:
	cd packages/edge-client && npm run dev
