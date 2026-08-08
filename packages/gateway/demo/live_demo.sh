#!/usr/bin/env bash
# Live end-to-end demo against a REAL running gateway (uvicorn, not TestClient).
# Boots the server on mock providers, exercises every feature over HTTP, tears
# down. No keys, no GPU, no Redis.
#
#   bash demo/live_demo.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PORT=8137
BASE="http://localhost:$PORT"

# Three keys: normal, a tight rate limit, and a tiny budget, to demo the guards.
export GW_API_KEYS_JSON='{"dev-key":{"tenant":"dev","rpm":120,"daily_usd":10},"rl":{"tenant":"rl","rpm":3,"daily_usd":10},"bg":{"tenant":"bg","rpm":120,"daily_usd":0.0005}}'
export GW_LOG_LEVEL=ERROR PYTHONPATH=src

uvicorn gateway.app:app --port "$PORT" --log-level error >/tmp/gw_live.log 2>&1 &
GW=$!
trap 'kill $GW 2>/dev/null || true' EXIT
until curl -sf "$BASE/healthz" >/dev/null 2>&1; do sleep 0.2; done

hr() { printf '%s\n' "------------------------------------------------------------"; }
# post KEY PROMPT [--schema]  -> prints one compact routing line
route() {
  local key="$1" prompt="$2" schema="${3:-}"
  local body
  if [ "$schema" = "--schema" ]; then
    body="{\"messages\":[{\"role\":\"user\",\"content\":\"$prompt\"}],\"json_schema\":{\"required\":[\"service\",\"root_cause\"],\"types\":{\"service\":\"string\",\"root_cause\":\"string\"}}}"
  else
    body="{\"messages\":[{\"role\":\"user\",\"content\":\"$prompt\"}]}"
  fi
  curl -s -X POST "$BASE/v1/chat/completions" -H "Authorization: Bearer $key" \
    -H 'Content-Type: application/json' -d "$body" \
  | python3 -c 'import sys,json
g=json.load(sys.stdin).get("x_gateway",{})
print("  tier=%-9s difficulty=%-7s esc=%s cache=%-5s cost=$%.5f" % (g.get("tier"),g.get("difficulty"),g.get("escalations"),g.get("cache_hit"),g.get("cost_usd")))'
}
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

echo "== health / readiness =="
echo "  /healthz -> $(code $BASE/healthz)   /readyz -> $(code $BASE/readyz)"
echo "  /v1/models -> $(curl -s $BASE/v1/models | python3 -c 'import sys,json;print([m["id"] for m in json.load(sys.stdin)["data"]])')"
hr
echo "== routing (OpenAI-compatible /v1/chat/completions) =="
route dev-key "What is the capital of France?"
route dev-key "Design a distributed rate limiter and reason about the consistency trade-offs."
route dev-key "Extract the failing service and root cause from this incident log." --schema
route dev-key "What is the capital of France?"   # cache hit
hr
echo "== streaming (SSE) =="
{ curl -s -N -X POST "$BASE/v1/chat/completions" -H "Authorization: Bearer dev-key" \
  -H 'Content-Type: application/json' \
  -d '{"stream":true,"messages":[{"role":"user","content":"Translate hi to Spanish"}]}' || true; } \
  | grep -m3 'data:' | sed 's/^/  /' || true
hr
echo "== guards =="
echo "  no auth        -> $(code -X POST $BASE/v1/chat/completions -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"hi"}]}')  (expect 401)"
for i in 1 2 3 4; do
  s=$(code -X POST $BASE/v1/chat/completions -H "Authorization: Bearer rl" -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"hi"}]}')
  echo "  rate-limit #$i -> $s$([ "$s" = 429 ] && echo '  (rpm=3 exceeded)')"
done
# Distinct hard prompts so each hits the frontier and accrues cost (identical
# prompts would be cache hits and never spend).
for i in 1 2 3; do
  s=$(code -X POST $BASE/v1/chat/completions -H "Authorization: Bearer bg" -H 'Content-Type: application/json' -d "{\"messages\":[{\"role\":\"user\",\"content\":\"Prove theorem $i step by step and analyze the distributed consistency trade-offs.\"}]}")
  echo "  budget #$i     -> $s$([ "$s" = 402 ] && echo '  (daily $0.0005 exhausted)')"
done
hr
echo "== Prometheus /metrics (selected) =="
curl -s "$BASE/metrics" | grep -E '^gw_(requests_total|cost_usd_total|escalations_total|cache_hits_total|rate_limited_total|budget_blocked_total)' | grep -v _created | sed 's/^/  /'
