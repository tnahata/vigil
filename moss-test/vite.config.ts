import { defineConfig, loadEnv } from "vite";
import wasm from "vite-plugin-wasm";
import topLevelAwait from "vite-plugin-top-level-await";

export default defineConfig(({ mode }) => {
  // Load ALL env vars (no prefix filter) so we can read MOSS_PROJECT_ID
  // in addition to VITE_MOSS_PROJECT_ID. Both forms are accepted.
  const env = loadEnv(mode, process.cwd(), "");

  const projectId  = env.VITE_MOSS_PROJECT_ID  || env.MOSS_PROJECT_ID  || "";
  const projectKey = env.VITE_MOSS_PROJECT_KEY || env.MOSS_PROJECT_KEY || "";

  return {
    // Inject credentials as compile-time constants so Vite exposes them to
    // the browser bundle regardless of which naming convention the user has.
    define: {
      __MOSS_PROJECT_ID__:  JSON.stringify(projectId),
      __MOSS_PROJECT_KEY__: JSON.stringify(projectKey),
    },

    // Prevent Vite from pre-bundling transformers.js — it uses dynamic model
    // imports that Vite cannot statically analyze.
    optimizeDeps: {
      // Exclude these from pre-bundling so their import.meta.url-based WASM
      // paths resolve correctly at runtime (pre-bundling relocates the file
      // and breaks the relative WASM URL). We use wasmUrl="/moss_wasm_bg.wasm"
      // in the MossClient constructor instead, served from public/.
      exclude: ["@huggingface/transformers", "@moss-dev/moss-web", "@moss-dev/moss-wasm"],
    },

    plugins: [
      // Handles .wasm files referenced via new URL('*.wasm', import.meta.url)
      // — exactly the pattern used by @moss-dev/moss-wasm.
      wasm(),
      topLevelAwait(),
      {
        // COOP + COEP are required for SharedArrayBuffer (threaded WASM).
        name: "cross-origin-isolation",
        configureServer(server) {
          server.middlewares.use((_req, res, next) => {
            res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
            res.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
            next();
          });
        },
      },
    ],
  };
});
