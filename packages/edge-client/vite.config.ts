import { defineConfig } from "vite";

// WebLLM pulls WebGPU/WASM at runtime; no special build config needed beyond
// letting Vite serve cross-origin isolation headers for best performance.
export default defineConfig({
  server: {
    headers: {
      // Enables SharedArrayBuffer / better WASM threading where supported.
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Embedder-Policy": "require-corp",
    },
  },
  build: { target: "es2022" },
});
