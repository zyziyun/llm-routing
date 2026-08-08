// Entry point. Picks engines based on what the device supports, then mounts
// the UI. The whole point is here:
//   - WebGPU present  -> local tier is a real in-browser model (WebLLM).
//   - No WebGPU       -> degrade gracefully to a mock local tier (or you could
//                        go cloud-only). The app still works, just less local.
//   - Cloud tier      -> your gateway if configured, else a mock for the demo.
//
// Provider API keys never live here. The cloud tier talks to YOUR gateway,
// which holds the keys. See DESIGN in the monorepo docs.

import { EdgeRouter } from "./core/router.ts";
import type { Engine } from "./engines/types.ts";
import { MockLocalEngine, MockCloudEngine } from "./engines/mock.ts";
import { WebLLMEngine, LOCAL_MODELS } from "./engines/webllm.ts";
import { CloudEngine } from "./engines/cloud.ts";
import { mountApp } from "./ui/app.ts";

// Configure a real gateway by setting these in the browser console once:
//   localStorage.setItem("gatewayUrl", "https://llm-gateway-xxxx.run.app")
//   localStorage.setItem("gatewayToken", "dev-key")
function cloudEngine(): Engine {
  const url = localStorage.getItem("gatewayUrl");
  const token = localStorage.getItem("gatewayToken");
  if (url && token) return new CloudEngine({ baseUrl: url, token });
  return new MockCloudEngine(); // demo mode: no backend needed
}

async function boot() {
  const status = document.getElementById("status")!;
  let local: Engine | null = null;
  let statusText: string;

  if (WebLLMEngine.webgpuAvailable()) {
    status.textContent = "WebGPU found. Loading a small model into your browser… (first load downloads weights, then they are cached)";
    const engine = new WebLLMEngine(LOCAL_MODELS.tiny, (p) => {
      status.innerHTML = `Loading local model… <progress value="${p.progress}" max="1"></progress> ${p.text}`;
    });
    const ok = await engine.ready();
    if (ok) {
      local = engine;
      statusText = `On-device model ready: <code>${LOCAL_MODELS.tiny}</code>. Easy turns stay local; hard ones escalate.`;
    } else {
      local = new MockLocalEngine();
      statusText = "Local model failed to load; using a mock local tier. The routing logic is identical.";
    }
  } else {
    local = new MockLocalEngine();
    statusText =
      "No WebGPU in this browser, so there is no real on-device model. Falling back to a mock local tier to demo the routing; use Chrome/Edge 113+ for the real thing.";
  }

  const router = new EdgeRouter(local, cloudEngine());
  mountApp(router, statusText);
}

boot();
