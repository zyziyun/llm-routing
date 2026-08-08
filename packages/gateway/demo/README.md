# Demos

Three ways to see the system run, from zero-setup to full stack.

## 1. Terminal monitoring demo (zero setup)

Drives the gateway with a scripted mix of requests and prints a live
dashboard: routing decisions, tier distribution, cost vs an all-frontier
baseline, cache hits, and a scrape of Prometheus `/metrics`. No server, no
keys, no GPU.

```bash
cd packages/gateway
PYTHONPATH=src python demo/demo.py
# or from the repo root: make demo
```

## 2. Full stack: gateway + Prometheus + Grafana

Real metrics scraped into Prometheus and graphed in Grafana.

```bash
docker compose -f deploy/docker-compose.yml up --build
# gateway :8000   prometheus :9090   grafana :3000 (admin/admin)
# then send traffic:
curl -X POST localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer dev-key" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is the capital of France?"}]}'
```

## 3. Browser frontend (on-device routing)

The edge client runs a small model in the browser and shows per-request tier,
escalation reason, PII redacted on device, and a live privacy/cost panel.

```bash
cd packages/edge-client
npm install && npm run dev   # Chrome/Edge 113+ for WebGPU
```
