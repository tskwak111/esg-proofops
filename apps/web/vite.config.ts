import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "../..", "");
  const api = env.API_PUBLIC_BASE_URL || "http://127.0.0.1:8000";
  return {
    envDir: "../..",
    plugins: [react()],
    server: {
      port: 5175,
      proxy: { "/v1": api, "/auth": api, "/local/uploads": api, "/local/sources": api,
        ...(env.LOCAL_ANALYSIS_API ? { "/api": { target: env.LOCAL_ANALYSIS_API, timeout: 900000, proxyTimeout: 900000 } } : {}),
      },
    },
  };
});
