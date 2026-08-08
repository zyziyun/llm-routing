# Deploying the gateway

Split the system into two parts with different hosting needs:

- **The gateway** (`src/gateway`, FastAPI). CPU-only. Needs an always-on host
  with a stable public HTTPS URL. This is what goes on a resume.
- **The model tiers**. The cloud tiers are just API calls. The self-hosted /
  edge tier (Ollama or vLLM small model) is the only part that wants a GPU.

Do not host the gateway on Colab or RunPod: Colab notebooks are ephemeral
with no stable URL, and RunPod is GPU rental. Use them for the model tier, not
the service.

---

## Path A — simplest portfolio deploy (no GPU)

Gateway on Cloud Run or Render; tiers are mock or a hosted API (OpenAI /
OpenRouter). Gives a public URL in minutes.

### Cloud Run

```bash
PROJECT=your-gcp-project
docker build -f Dockerfile.gateway -t gcr.io/$PROJECT/llm-gateway .
docker push gcr.io/$PROJECT/llm-gateway

gcloud run deploy llm-gateway \
  --image gcr.io/$PROJECT/llm-gateway \
  --region us-central1 --allow-unauthenticated \
  --min-instances 1 --max-instances 1 \
  --set-env-vars WEB_CONCURRENCY=1,GW_ENV=prod
```

`--max-instances 1` + `WEB_CONCURRENCY=1` keeps the in-memory store correct
(one process holds cache/breaker/budget). To scale beyond one instance, add
Redis (below) and drop these limits.

### Render (even simpler)

Point Render at the repo, Docker env, Dockerfile path `Dockerfile.gateway`,
health check `/healthz`. It builds and gives an HTTPS URL.

### Shared state for multi-instance (Upstash, serverless Redis, free tier)

```bash
gcloud run services update llm-gateway \
  --set-env-vars GW_REDIS_URL=rediss://default:TOKEN@your-db.upstash.io:6379 \
  --max-instances 10
```

With Redis set, cache / circuit breaker / rate limit / budget are shared, so
you can scale horizontally and raise WEB_CONCURRENCY.

---

## Path B — make the self-hosted edge tier real (uses your RunPod GPU)

This is the level-up: the EDGE tier becomes an actual small model you host,
not a mock. It produces genuine cost/quality eval numbers and backs a
"self-hosted open-source model" resume bullet.

1. On RunPod, start a GPU pod with Ollama (or an Ollama template). Pull a
   small model and expose the port:

   ```bash
   ollama serve &
   ollama pull llama3.2:3b        # or qwen3:4b, phi4-mini, gpt-oss:20b
   ```

   RunPod gives a proxy URL like `https://<pod-id>-11434.proxy.runpod.net`.

2. Point the gateway's EDGE tier at it (env on Cloud Run / Render):

   ```
   GW_EDGE_BACKEND=ollama
   OLLAMA_HOST=https://<pod-id>-11434.proxy.runpod.net
   EDGE_MODEL=llama3.2:3b
   ```

   Alternatively run vLLM on RunPod for an OpenAI-compatible endpoint and use
   it as the CHEAP tier: `GW_CHEAP_BACKEND=openai`,
   `OPENAI_BASE_URL=https://<pod>-8000.proxy.runpod.net/v1`.

3. Keep FRONTIER on a hosted API (`GW_FRONTIER_BACKEND=openai`) so hard
   requests still escalate to a strong model.

RunPod bills by GPU-hour, so bring the pod up to record eval numbers and to
demo, then stop it. The gateway keeps serving on cheap/frontier when EDGE is
down, thanks to the circuit breaker.

---

## Colab

Fine for a throwaway demo or to generate eval results in a notebook: run the
gateway (or a local model) and expose it with a cloudflared tunnel. Not for a
persistent URL, because the session and tunnel die. Use Path A for anything
that has to stay up.

---

## What actually matters for the portfolio

A public URL on Cloud Run running Path A (even on mock or a cheap hosted API)
is enough to satisfy "HM can click it." Path B with RunPod is the upgrade
that makes the self-hosted-SLM story real and the eval numbers your own.
