// Engine interface. A tier (local on-device, or cloud) implements this. The
// router depends only on this, so tests use mocks, the browser uses WebLLM,
// and the cloud tier calls your gateway. Same contract everywhere.

import type { EngineReply, RouterRequest } from "../core/types.ts";

export interface Engine {
  tier: "local" | "cloud";
  model: string;
  ready(): Promise<boolean>;
  complete(req: RouterRequest): Promise<EngineReply>;
  // Optional token streaming for UI responsiveness.
  stream?(req: RouterRequest): AsyncIterable<string>;
}
